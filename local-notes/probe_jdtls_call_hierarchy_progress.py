import json, subprocess, threading, time, os

BASE = "/Users/zhangdi/Library/Application Support/ZedLocalPatch/extensions/work/java"
JAVA = BASE + "/jdk/25.0.5.1.2/amazon-corretto-25.jdk/Contents/Home/bin/java"
JDTLS = BASE + "/jdtls/1.63.0"
LAUNCHER = JDTLS + "/plugins/org.eclipse.equinox.launcher_1.8.0.v20260804-1928.jar"
CONFIG = JDTLS + "/config_mac"
LOMBOK = BASE + "/lombok/lombok-1.18.48.jar"

# 自包含：需要时创建最小 Java 工程
PROJECT = "/tmp/jdtls-probe"
HELLO = PROJECT + "/src/main/java/probe/Hello.java"
os.makedirs(os.path.dirname(HELLO), exist_ok=True)
if not os.path.exists(HELLO):
    with open(HELLO, "w") as f:
        f.write(
            "package probe;\n\n"
            "public class Hello {\n"
            "    public static void main(String[] args) {\n"
            "        helper();\n"
            "    }\n\n"
            "    static void helper() {\n"
            '        System.out.println("hi");\n'
            "    }\n"
            "}\n"
        )

args = [
    JAVA, "-Declipse.application=org.eclipse.jdt.ls.core.id1",
    "-Dosgi.bundles.defaultStartLevel=4",
    "-Declipse.product=org.eclipse.jdt.ls.core.product",
    "-Dosgi.checkConfiguration=true",
    "-Dosgi.sharedConfiguration.area=" + CONFIG,
    "-Dosgi.sharedConfiguration.area.readOnly=true",
    "-Dosgi.configuration.cascaded=true",
    "-Djava.import.generatesMetadataFilesAtProjectRoot=false",
    "-Djava.net.preferIPv4Stack=true",
    "-Xms512m", "--add-modules=ALL-SYSTEM",
    "--add-opens", "java.base/java.util=ALL-UNNAMED",
    "--add-opens", "java.base/java.lang=ALL-UNNAMED",
    "-javaagent:" + LOMBOK, "-jar", LAUNCHER, "-nosplash",
    "-data", "/tmp/jdtls-probe-data",
]

proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, bufsize=0)
lock = threading.Lock()
next_id = [0]
events = []

def send(msg):
    body = json.dumps(msg).encode()
    with lock:
        proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        proc.stdin.flush()

def reader():
    f = proc.stdout
    while True:
        headers = {}
        line = f.readline()
        if not line:
            return
        while line not in (b"\r\n", b"\n", b""):
            k, _, v = line.decode().partition(":")
            headers[k.strip().lower()] = v.strip()
            line = f.readline()
        n = int(headers.get("content-length", 0))
        body = f.read(n)
        try:
            msg = json.loads(body)
        except Exception:
            continue
        with lock:
            events.append((time.time(), msg.get("method") or ("response:%s" % msg.get("id")), msg))

threading.Thread(target=reader, daemon=True).start()

def rpc(method, params):
    next_id[0] += 1
    i = next_id[0]
    send({"jsonrpc": "2.0", "id": i, "method": method, "params": params})
    return i

def wait_for(i, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        with lock:
            for t, kind, msg in events:
                if kind == "response:%s" % i:
                    return msg, t
        time.sleep(0.01)
    return None, None

def clear():
    with lock:
        events.clear()

def ends_since(t0):
    with lock:
        out = []
        for t, kind, msg in events:
            if kind == "$/progress":
                val = msg.get("params", {}).get("value", {})
                if val.get("kind") == "end":
                    out.append(t - t0)
        return out

root = "file:///tmp/jdtls-probe"
i = rpc("initialize", {
    "processId": os.getpid(), "rootUri": root,
    "capabilities": {
        "window": {"workDoneProgress": True},
        "textDocument": {"callHierarchy": {"dynamicRegistration": True},
                          "synchronization": {"didSave": True},
                          "publishDiagnostics": {}},
        "workspace": {"workspaceFolders": True, "configuration": True},
    },
    "workspaceFolders": [{"uri": root, "name": "probe"}],
})
wait_for(i, 90)
send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
time.sleep(3)

path = "/tmp/jdtls-probe/src/main/java/probe/Hello.java"
uri = "file://" + path
send({"jsonrpc": "2.0", "method": "textDocument/didOpen",
      "params": {"textDocument": {"uri": uri, "languageId": "java", "version": 1,
                                    "text": open(path).read()}}})

# warm up until quiet
time.sleep(12)
clear()
t0 = time.time()
time.sleep(5)
idle_ends = ends_since(t0)
print("IDLE 5s: progress ends =", len(idle_ends))

# empty position (no callable symbol) -> jdtls returns empty list
for round_no in range(1, 4):
    clear()
    t0 = time.time()
    pid = rpc("textDocument/prepareCallHierarchy",
              {"textDocument": {"uri": uri}, "position": {"line": 0, "character": 0}})
    resp, tresp = wait_for(pid, 30)
    result = resp.get("result") if resp else "NO RESPONSE"
    time.sleep(4)
    with lock:
        ends = [(t - t0) for t, kind, msg in events
                if kind == "$/progress" and msg.get("params", {}).get("value", {}).get("kind") == "end"]
    after = [x for x in ends if tresp and x > (tresp - t0)]
    print(f"ROUND {round_no}: result={result if not isinstance(result, list) else ('list len ' + str(len(result)))}"
          f" | response at {tresp - t0:.3f}s | progress ends total={len(ends)} after_response={len(after)}")

# burst of 5 fast prepares
clear()
t0 = time.time()
for _ in range(5):
    rpc("textDocument/prepareCallHierarchy",
        {"textDocument": {"uri": uri}, "position": {"line": 0, "character": 0}})
    time.sleep(0.01)
time.sleep(5)
print("BURST 5 prepares: progress ends =", len(ends_since(t0)))

try:
    rpc("shutdown", None)
    time.sleep(0.4)
    send({"jsonrpc": "2.0", "method": "exit", "params": None})
except Exception:
    pass
time.sleep(0.4)
proc.kill()
