import { chromium } from 'playwright';

// Função para fazer login no Chaves na Mão
export default async function handler(req, res) {
  // Configurar CORS
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

  let browser = null;
  
  try {
    // Iniciar browser
    browser = await chromium.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });

    const page = await browser.newPage();
    
    // Acessar página de login
    await page.goto('https://www.chavesnamao.com.br/entrar/', { 
      waitUntil: 'networkidle',
      timeout: 30000 
    });

    // Clicar em "Entrar com email"
    await page.click('span.spacing-1x > button');
    await page.waitForTimeout(2000);

    // Preencher credenciais
    await page.fill('#userLogin-input', email);
    await page.fill('input[type="password"]', senha);
    
    // Clicar no botão de entrar
    await page.click('button[type="submit"]');
    await page.waitForTimeout(5000);

    const currentUrl = page.url();
    
    // Verificar se login foi bem-sucedido
    if (currentUrl.includes('minhaconta') || !currentUrl.includes('entrar')) {
      // Login bem-sucedido
      const sessionToken = Buffer.from(`${email}:${Date.now()}`).toString('base64');
      
      // Salvar cookies para uso posterior
      const cookies = await page.context().cookies();
      
      await browser.close();

      return res.status(200).json({
        success: true,
        sessionToken,
        cookies,
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
    if (browser) await browser.close();
    return res.status(500).json({ 
      success: false, 
      error: error.message 
    });
  }
}
