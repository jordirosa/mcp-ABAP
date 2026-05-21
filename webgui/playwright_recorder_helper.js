const args = process.argv.slice(2);

function arg(name, fallback = "") {
  const index = args.indexOf(name);
  if (index === -1 || index + 1 >= args.length)
    return fallback;
  return args[index + 1];
}

async function main() {
  const playwrightPackage = arg("--package", "playwright");
  const cdpEndpoint = arg("--cdp");
  const pageUrl = arg("--url");
  const outputFile = arg("--output");
  const ignoreHTTPSErrors = arg("--ignore-https-errors") === "true";

  if (!cdpEndpoint)
    throw new Error("--cdp is required");
  if (!outputFile)
    throw new Error("--output is required");

  const { chromium } = require(playwrightPackage);
  const browser = await chromium.connectOverCDP(cdpEndpoint);
  const contexts = browser.contexts();
  let context = contexts.find(candidate =>
    candidate.pages().some(page => page.url() === pageUrl)
  );
  if (!context)
    context = contexts.find(candidate => candidate.pages().length > 0) || contexts[0];
  if (!context)
    throw new Error("No browser context found over CDP.");

  if (typeof context._enableRecorder !== "function")
    throw new Error("Connected context does not expose _enableRecorder.");

  await context._enableRecorder({
    language: "playwright-test",
    launchOptions: {},
    contextOptions: { ignoreHTTPSErrors },
    mode: "recording",
    outputFile,
    handleSIGINT: false
  });

  console.log("READY");

  process.stdin.setEncoding("utf8");
  process.stdin.on("data", async chunk => {
    if (!chunk.toString().toLowerCase().includes("stop"))
      return;
    try {
      if (typeof context._disableRecorder === "function")
        await context._disableRecorder();
      await new Promise(resolve => setTimeout(resolve, 500));
      console.log("STOPPED");
      process.exit(0);
    } catch (error) {
      console.error(error && error.stack ? error.stack : String(error));
      process.exit(1);
    }
  });
}

main().catch(error => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
