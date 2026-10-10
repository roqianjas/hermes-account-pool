(function () {
  "use strict";
  // account-pool: the page lives in Hermes Desktop (Accounts in the sidebar). This file only
  // registers the plugin so the browser dashboard does not report it as broken; its tab is hidden.
  var plugins = window.__HERMES_PLUGINS__;
  var SDK = window.__HERMES_PLUGIN_SDK__;
  if (!plugins || !SDK) return;
  plugins.register("account-pool", function AccountPool() {
    return SDK.React.createElement("p", { style: { padding: 16 } },
      "Open Hermes Desktop and choose Accounts in the sidebar, or run: hermes account anthropic usage");
  });
})();
