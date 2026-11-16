const {test, expect}=require('@playwright/test');
const path=require('path');
test('dashboard shows groups, safely renders email text and submits parcel actions', async ({page})=>{
  await page.setContent('<html><head><style>body{font-family:Arial;background:#eef2f5;padding:24px}ha-card{background:white;max-width:640px;margin:auto;border-radius:20px;box-shadow:0 4px 20px #ccd}</style></head><body></body></html>');
  await page.addScriptTag({path:path.resolve('custom_components/packages_esp/www/packages-esp-card.js')});
  await page.evaluate(()=>{
    const parcel={id:'sample1',retailer:'Amazon',description:'<img src=x onerror=alert(1)> Test headphones',carrier:'Amazon',status:'in_transit',expected_date:'2026-11-16',confidence:'medium',updated_at:'2026-11-16T09:00:00Z'};
    const pickup={id:'sample2',retailer:'Leroy Merlin',description:'Water filter',status:'ready_for_pickup',pickup_deadline:'2026-11-18',confidence:'high',pickup_location:'Test pickup point'};
    window.calls=[];
    const card=document.createElement('packages-esp-card');
    card.setConfig({entry_id:'account1',language:'en'});
    document.body.append(card);
    card.hass={language:'en',callWS:async(request)=>{
      window.calls.push(request);
      if(request.service==='get_deliveries' && request.service_data.parcel_id) return {response:{parcel:{...parcel,tracking_url:'javascript:alert(1)',source_url:'https://mail.google.com/mail/u/0/#all/test'},history:[{source:'Amazon'}]}};
      return {response:{groups:{today:[parcel],tomorrow:[],pickups_ready:[pickup],attention:[],upcoming:[],unknown:[]},stale:false,initial_import:false}};
    }};
  });
  await expect(page.getByText('Today · 1')).toBeVisible();
  await expect(page.getByText('Ready to collect · 1')).toBeVisible();
  await expect(page.locator('img')).toHaveCount(0);
  await page.getByRole('button',{name:'Details',exact:true}).first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('link',{name:'Track parcel'})).toHaveCount(0);
  await expect(page.getByRole('link',{name:'Source email'})).toHaveAttribute('href','https://mail.google.com/mail/u/0/#all/test');
  await page.screenshot({path:'test-results/deliveries-desktop.png',fullPage:true});
  await page.getByRole('button',{name:'Mark collected',exact:true}).click();
  const calls=await page.evaluate(()=>window.calls);
  expect(calls.some(c=>c.service==='mark_collected' && c.service_data.parcel_id==='sample1' && c.service_data.entry_id==='account1')).toBeTruthy();
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'test-results/deliveries-mobile.png',fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});
