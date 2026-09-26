import puppeteer from 'puppeteer-core'
const browser = await puppeteer.launch({
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: 'new',
})
const page = await browser.newPage()
await page.setViewport({ width: 1280, height: 900, deviceScaleFactor: 2 })
await page.goto('https://github.com/uoparaji/agentlens', { waitUntil: 'networkidle2' })
await new Promise((r) => setTimeout(r, 2500))
await page.evaluate(() => document.querySelector('article.markdown-body img').scrollIntoView({ block: 'center' }))
await new Promise((r) => setTimeout(r, 1200))
const box = await page.evaluate(() => {
  const r = document.querySelector('article.markdown-body img').getBoundingClientRect()
  return { x: r.x, y: r.y, width: r.width, height: r.height }
})
console.log('banner box now:', JSON.stringify(box))
await page.screenshot({
  path: '/tmp/gh-banner.png',
  clip: { x: box.x - 30, y: box.y - 30, width: box.width + 60, height: box.height + 60 },
})
await browser.close()
