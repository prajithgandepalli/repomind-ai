import assert from 'node:assert/strict'
import {randomBytes} from 'node:crypto'
import test from 'node:test'
import {chromium} from 'playwright-core'

test('authenticated repository, citations, history and deletion', {timeout:240000}, async()=>{
  const base=process.env.REPOMIND_TEST_URL
  assert.ok(base,'Set REPOMIND_TEST_URL to an isolated test deployment.')
  const browser=await chromium.launch({channel:process.env.BROWSER_CHANNEL||'msedge'})
  try{
    const page=await browser.newPage({viewport:{width:390,height:844}})
    page.setDefaultTimeout(20000)
    const email='browser-'+Date.now()+'@example.com',password=randomBytes(24).toString('hex')
    async function login(){
      await page.locator('[name=email]').fill(email)
      await page.locator('[name=password]').fill(password)
      await page.getByRole('button',{name:'Sign in'}).click()
      await page.getByLabel('Public GitHub URL').waitFor()
    }
    await page.goto(base+'/dashboard')
    await page.waitForURL('**/login')
    await page.getByRole('link',{name:'Create an account'}).click()
    await page.locator('[name=username]').fill('BrowserTest')
    await page.locator('[name=email]').fill(email)
    await page.locator('[name=password]').fill(password)
    await page.getByRole('button',{name:'Create account'}).click()
    await page.waitForURL('**/login?registered=1')
    await login()
    await page.getByLabel('Public GitHub URL').fill('https://github.com/pypa/sampleproject')
    await page.getByRole('button',{name:'Retrieve source'}).click()
    await page.getByRole('link',{name:'Open chat'}).waitFor({timeout:130000})
    const sha=await page.locator('.repos article small code').innerText()
    await page.getByRole('link',{name:'Open chat'}).click()
    const question='What do the retrieved Python files do?'
    await page.getByLabel('Your question').fill(question)
    await page.getByRole('button',{name:'Ask RepoMind'}).click()
    const link=page.locator('.citations a').first()
    await link.waitFor({timeout:120000})
    const url=await link.getAttribute('href')
    assert.ok(url.startsWith('https://github.com/pypa/sampleproject/blob/'+sha+'/'))
    assert.match(url,/#L\d+-L\d+$/)
    await page.reload()
    assert.equal(await link.getAttribute('href'),url)
    await page.getByRole('link',{name:'Workspace',exact:false}).click()
    await page.getByRole('button',{name:'Sign out'}).click()
    await page.waitForURL('**/login')
    await login()
    await page.getByRole('link',{name:'Open chat'}).click()
    assert.equal(await link.getAttribute('href'),url)
    page.on('dialog',d=>d.accept())
    await page.getByRole('button',{name:'Delete chat'}).click()
    await page.getByText('Ask about the code in this commit.').waitFor()
    await page.getByRole('link',{name:'Workspace',exact:false}).click()
    await page.getByRole('button',{name:'Delete',exact:true}).click()
    await page.getByText('No repositories added yet.').waitFor()
    console.log('Verified commit-pinned citation',url)
  }finally{await browser.close()}
})

