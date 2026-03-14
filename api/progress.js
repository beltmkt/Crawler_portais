import { createClient } from '@vercel/kv';

const kv = createClient({
  url: process.env.KV_REST_API_URL,
  token: process.env.KV_REST_API_TOKEN,
});

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Cache-Control', 'no-cache');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  const { jobId } = req.query;

  if (!jobId) {
    return res.status(400).json({ error: 'jobId é obrigatório' });
  }

  try {
    const job = await kv.get(`job:${jobId}`);

    if (!job) {
      return res.status(404).json({ error: 'Job não encontrado' });
    }

    return res.status(200).json({
      status: job.status || 'running',
      total: job.total || 0,
      processed: job.processed || 0,
      photos: job.photos || 0,
      logs: job.logs || [],
      xml: job.xml || null
    });

  } catch (error) {
    console.error('Erro ao buscar progresso:', error);
    return res.status(500).json({ error: error.message });
  }
}
