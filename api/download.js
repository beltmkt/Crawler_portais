import { createClient } from '@vercel/kv';

const kv = createClient({
  url: process.env.KV_REST_API_URL,
  token: process.env.KV_REST_API_TOKEN,
});

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  const { jobId } = req.query;

  if (!jobId) {
    return res.status(400).json({ error: 'jobId é obrigatório' });
  }

  try {
    const job = await kv.get(`job:${jobId}`);

    if (!job || !job.xml) {
      return res.status(404).json({ error: 'XML não encontrado' });
    }

    res.setHeader('Content-Type', 'application/xml');
    res.setHeader('Content-Disposition', `attachment; filename="imoveis_${jobId}.xml"`);
    
    return res.status(200).send(job.xml);

  } catch (error) {
    console.error('Erro ao baixar XML:', error);
    return res.status(500).json({ error: error.message });
  }
}
