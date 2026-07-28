import { createServer } from "node:http";
import next from "next";

const HOST = "127.0.0.1";
const PORT = 3100;
const READY_TEXT = "aira-e2e-ready";

const app = next({ dev: true, dir: process.cwd(), hostname: HOST, port: PORT });
const handle = app.getRequestHandler();

await app.prepare();

const server = createServer((request, response) => {
  if (request.url === "/__aira_e2e_health") {
    response.writeHead(200, { "content-type": "text/plain", connection: "close" });
    response.end(READY_TEXT);
    return;
  }

  if (request.url === "/__aira_e2e_shutdown" && request.method === "POST") {
    response.writeHead(202, { "content-type": "text/plain", connection: "close" });
    response.end("shutting down");
    setImmediate(async () => {
      server.closeAllConnections();
      await new Promise((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      });
      await app.close();
      process.exit(0);
    });
    return;
  }

  void handle(request, response);
});

server.on("upgrade", app.getUpgradeHandler());

await new Promise((resolve, reject) => {
  server.once("error", reject);
  server.listen(PORT, HOST, () => {
    server.off("error", reject);
    resolve();
  });
});
