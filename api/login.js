import { chromium } from 'playwright';
import { createClient } from '@vercel/kv';

const kv = createClient({
  url: process.env.KV_REST_API_URL,
  token: process.env.KV_REST_API_TOKEN,
});

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Método não permitido' });
  }

  const { email, senha } = req.body;

  if (!email || !senha) {
    return res.status(400).json({ error: 'Email e senha obrigatórios' });
  }

  try {
    const browser = await chromium.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });

    const page = await browser.newPage();
    
    await page.goto('https://www.chavesnamao.com.br/entrar/', { 
      waitUntil: 'networkidle',
      timeout: 30000 
    });

    await page.click('span.spacing-1x > button');
    await page.waitForTimeout(2000);

    await page.fill('#userLogin-input', email);
    await page.fill('input[type="password"]', senha);
    
    await page.click('button[type="submit"]');
    await page.waitForTimeout(5000);

    const currentUrl = page.url();
    
    if (currentUrl.includes('minhaconta') || !currentUrl.includes('entrar')) {
      const sessionToken = Buffer.from(`${email}:${Date.now()}`).toString('base64');
      
      await kv.set(`session:${sessionToken}`, {
        email,
        createdAt: Date.now(),
        cookies: await page.context().cookies()
      }, { ex: 3600 });

      await browser.close();

      return res.status(200).json({
        success: true,
        sessionToken,
        message: 'Login realizado com sucesso'
      });
    } else {
      await browser.close();
      return res.status(401).json({ 
        success: false, 
        error: 'Falha no login. Verifique suas credenciais.' 
      });
    }

  } catch (error) {
    console.error('Erro no login:', error);
    return res.status(500).json({ 
      success: false, 
      error: error.message 
    });
  }
}
