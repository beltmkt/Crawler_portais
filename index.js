export default function handler(req, res) {
  res.status(200).json({ 
    status: "ok", 
    message: "Chaves Exporter API está funcionando!",
    endpoints: {
      login: "/api/login",
      extract: "/api/extract",
      progress: "/api/progress?jobId=XXX",
      download: "/api/download?jobId=XXX"
    }
  });
}
