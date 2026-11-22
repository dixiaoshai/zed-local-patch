use client::ZED_URL_SCHEME;
use gpui::{AsyncApp, actions};
use release_channel::{RELEASE_CHANNEL, ReleaseChannel};

actions!(
    cli,
    [
        /// Registers the zed:// URL scheme handler.
        RegisterZedScheme
    ]
);

pub async fn register_zed_scheme(cx: &AsyncApp) -> anyhow::Result<()> {
    if *RELEASE_CHANNEL == ReleaseChannel::Dev {
        return Ok(());
    }

    cx.update(|cx| cx.register_url_scheme(ZED_URL_SCHEME)).await
}
