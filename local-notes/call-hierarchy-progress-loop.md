# 调用层级面板 × jdtls：请求死循环的定位与修复

> 状态：已在 `local-patch` 分支修复（2026-11-23），并已用修复后的源码重新构建、安装到 `~/Applications/Zed Local Patch.app`。修复前的表现是「打开调用层级后风扇常转，jdtls 长期占 46% CPU」。
>
> 结论：Zed 的调用层级面板会把「自己的 `prepareCallHierarchy` 请求产生的进度通知」当成「语言服务器就绪」信号，从而无限重发请求。修复后只允许**请求发出前已经在进行的语言服务器工作**结束时触发一次重试，请求自身产生的进度不再触发任何重试。

## 1. 现象

- `Zed Local Patch`（Zed 1.29.2 本地构建）打开「调用层级」（Call Hierarchy）面板后，若光标处没有可调用符号，面板显示 `No callable symbol under the cursor`。
- 此后 jdtls 进程持续占约 46% CPU（单线程 81%），风扇长转，可长达数小时。
- Zed 自身约 28% CPU、WindowServer 约 25%，日志中该语言服务器的请求号膨胀到 **1,715,029**（约 79 次/秒）。

## 2. 根因

### 2.1 现场证据

1. `~/Library/Logs/ZedLocalPatch/ZedLocalPatch.log` 在终止语言服务器瞬间：

   ```
   ERROR [lsp] Server reset connection for a request "textDocument/prepareCallHierarchy" id 1715029
   WARN  [project::lsp_store] Prepare call hierarchy via jdtls failed: Server reset the connection
   ```

2. jdtls 进程采样：单线程 81% CPU，栈顶固定为 `CallHierarchyHandler.prepareCallHierarchy → JDTUtils.toLocation → ResourceUtils.fixURI → String.replaceFirst → Pattern.compile`。

3. 独立实验（不经过 Zed，最小 LSP 客户端直连 jdtls 1.63.0，脚本见 `probe_jdtls_call_hierarchy_progress.py`）：

   | 测量项 | 结果 |
   | --- | --- |
   | 预热后空闲 5 秒收到的 `$/progress` end | **0 个** |
   | 发 1 次 `textDocument/prepareCallHierarchy`（返回空） | **恰好 1 个** end |
   | 连发 5 次 | **恰好 5 个** end |

   即「一次 prepare 请求 = 一个 WorkEnd 事件」，闭环成立。

### 2.2 jdtls 侧

反编译 `JDTLanguageServer.prepareCallHierarchy` 可见它走 `computeAsyncWithClientProgress(...)`：每次请求都会创建一个客户端可见的进度组（`window/workDoneProgress/create` + `$/progress` begin/report/end）。Zed 初始化时声明支持 `window.workDoneProgress`，所以这些通知会全量送达 Zed 并转成 `LspStoreEvent::LanguageServerUpdate::WorkEnd`。

### 2.3 Zed 侧（修复前的代码路径）

```
prepareCallHierarchy 请求
  → jdtls 返回 null（光标处无符号）
  → jdtls 结束该请求的进度组，发 $/progress end
  → lsp_store::on_lsp_work_end 广播 WorkEnd
  → call_hierarchy 视图收到 WorkEnd（不区分来源）
  → retry_empty_hierarchy：root_item 为空就再 fetch_root
  → fetch_root 没有 in-flight 守卫，直接再发请求
  → 回到第一步（79 次/秒）
```

关键点：`retry_empty_hierarchy` 只判断 `root_item.is_none()`，于是**自己请求触发的 WorkEnd** 也会导致再请求，形成自持循环；每次重试还 `cx.notify()` 重绘面板，所以 WindowServer 也跟着忙。

## 3. 修复方案

### 3.1 核心思路

「语言服务器空闲了，值得再问一次」这个信号只可能来自**在请求发出之前就已经在进行的工作**（例如索引、导入项目）。请求自身引起的进度（jdtls 每次 prepare 都会产生一个）绝不应该是重试依据。

因此：

1. 视图维护「当前进行中的语言服务器工作 token」集合（`WorkStart` 加入、`WorkEnd` 移除，打开面板时用 `LspStore::language_server_statuses().pending_work` 初始化，覆盖「打开面板前就已经在索引」的场景）；
2. 每次发 prepare 请求**之前**，把当前进行中的 token 快照到 `retry_after_work_end`；
3. 收到 `WorkEnd` 时，只有该 token 在快照里（且消费后移除）才重试；
4. 再加一层保险：最多自动重试 `MAX_FETCH_RETRIES = 8` 次，加载中的请求不重试，拿到根条目后清空快照。

这样，jdtls 的 prepare 请求产生的进度 token 永远不在快照里 → 不再重试 → 循环不可能成立；而 Rust Analyzer 等「打开面板时仍在建索引」的场景，索引的 token 在快照里，索引结束时仍会刷新一次。

### 3.2 代码改动

| 文件 | 改动 |
| --- | --- |
| `crates/call_hierarchy/src/call_hierarchy.rs` | 新增 `active_work_tokens`、`retry_after_work_end`、`retry_count`；订阅 `WorkStart`/`WorkEnd` 并在 `WorkEnd` 时按快照过滤；`fetch_root` 发请求前快照、成功后清空；`retry_empty_hierarchy` 增加 `Loading` 守卫与重试上限 `MAX_FETCH_RETRIES` |
| `crates/project/src/lsp_store.rs` | `ProgressToken::from_proto` / `to_proto` 改为 `pub`，供其它 crate 在事件中还原 token |
| `crates/call_hierarchy/Cargo.toml` | 增加 `lsp` 依赖（事件中的 `LanguageServerId`） |

### 3.3 防护层次

1. **根因**：只重试「请求发出前已在进行的语言服务器工作」；
2. **上限**：一次面板打开最多自动重试 8 次；
3. **状态守卫**：`FetchState::Loading` 期间不重试；
4. **清理**：拿到根条目后清空待重试 token，避免在结果到达后继续触发。

## 4. 测试

`crates/call_hierarchy/src/call_hierarchy.rs` 中：

- `test_call_hierarchy_modal_refreshes_on_lsp_work_end`（改写）：用 `fake_server.start_progress/end_progress` 模拟「打开面板时已有两项工作在进行」，断言工作结束触发**一次**重试，且后续工作结束能刷新出结果；
- `test_call_hierarchy_modal_ignores_progress_from_its_own_request`（新增，回归测试）：模拟 jdtls 行为——`prepareCallHierarchy` 请求自身产生一个进度组，断言它结束后**不会**再次发出 prepare 请求；
- `test_call_hierarchy_modal_refreshes_on_buffer_registration` / `test_call_hierarchy_modal_no_symbol` 保持原有行为。

运行：

```sh
export CARGO_HOME="$PWD/.local-build/cargo" RUSTUP_HOME="$PWD/.local-build/rustup"
export PATH="$PWD/.local-build/cmake-3.31.8-macos-universal/CMake.app/Contents/bin:$CARGO_HOME/bin:$PATH"
cargo +1.98.1 test -p call_hierarchy
```

验证结果：**22 个测试全部通过**，其中包含新增的回归测试 `test_call_hierarchy_modal_ignores_progress_from_its_own_request`。

## 5. 复现脚本

`probe_jdtls_call_hierarchy_progress.py` 是不依赖 Zed 的最小 LSP 客户端，读取本机 `ZedLocalPatch` 扩展目录中的 jdtls 1.63.0 与 Corretto 25，自动创建最小 Java 工程后测量：

```sh
python3 probe_jdtls_call_hierarchy_progress.py
```

输出应显示：预热后空闲期 0 个 progress end；每次 prepare 请求恰好 1 个 end；连发 5 次恰好 5 个。

## 6. 手动验证修复

1. 用仓库源码重新构建并安装：`cargo +1.98.1 build --release --target-dir target -p zed --bin zedlocalpatch && script/bundle-local-patch-mac`，再替换 `~/Applications/Zed Local Patch.app`；
2. 打开 Java 项目，把光标放到类名/注解等非可调用位置，打开「调用层级」；
3. 观察 `top -pid <jdtls pid>`：jdtls 应保持个位数 CPU；面板只显示 `No callable symbol under the cursor`，不再刷新；
4. 在 Rust 项目里验证原有用例：项目还在索引时打开调用层级，索引结束后面板仍会自动刷新出结果。

## 7. 相关文件

- 修复：`crates/call_hierarchy/src/call_hierarchy.rs`、`crates/project/src/lsp_store.rs`、`crates/call_hierarchy/Cargo.toml`
- 构建/安装：`script/bundle-local-patch-mac`、`.local-build/README.md`
- 复现：`local-notes/probe_jdtls_call_hierarchy_progress.py`

## 8. 构建与安装记录（2026-11-23）

- 构建命令（本地工具链，受内存限制用 `-j 4`）：

  ```sh
  export CARGO_HOME="$PWD/.local-build/cargo" RUSTUP_HOME="$PWD/.local-build/rustup"
  export PATH="$PWD/.local-build/cmake-3.31.8-macos-universal/CMake.app/Contents/bin:$CARGO_HOME/bin:$PATH"
  export ZED_UPDATE_EXPLANATION='Local build: apply patch and rebuild to update' CARGO_INCREMENTAL=0
  env -u ZED_RELEASE_CHANNEL cargo +1.98.1 build --locked --release --target-dir target -j 4 \
    -p zed --bin zedlocalpatch
  ```

  耗时约 68 分钟（中间因 12 路并行把 16GB 内存打满、Swap 超 10GB 而不得不中止重来）。

- 打包：`script/bundle-local-patch-mac` → `.local-build/Zed Local Patch Release.app`（ad-hoc 签名，`codesign --verify --deep --strict` 通过）。
- 安装：替换 `~/Applications/Zed Local Patch.app`，新二进制 399,029,216 字节（2026-11-23 22:10）；旧版备份在
  `~/Applications/Zed Local Patch.before-call-hierarchy-fix-20261123.app`。
- **生效方式**：退出当前正在运行的 Zed 并重新打开（运行中的实例仍是旧二进制）。
- 回滚：

  ```sh
  rm -rf "$HOME/Applications/Zed Local Patch.app"
  mv "$HOME/Applications/Zed Local Patch.before-call-hierarchy-fix-20261123.app" "$HOME/Applications/Zed Local Patch.app"
  ```
