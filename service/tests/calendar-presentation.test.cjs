// Execute the real form boundary functions without starting a browser or model server.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),test=require('node:test'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/calendar.js'),'utf8').replace(/\r\n/g,'\n');
const fields=new Map();
function field(id){if(!fields.has(id))fields.set(id,{value:'',checked:false,hidden:false,childNodes:[{textContent:''}]});return fields.get(id)}
const context={document:{getElementById:field},window:{},Intl,Date,WeakMap,URL,URLSearchParams};
const anchor='\n init();\n})();';assert(source.includes(anchor));
vm.runInNewContext(source.replace(anchor,'\n window.boundary={setDateFields,buildEvent,validateEvent,toggleAllDayMode,setEditor:v=>editor=v};\n})();'),context);
const api=context.window.boundary;
function base(){fields.clear();api.setEditor(null);field('event-title').value='합성 일정';field('event-kind').value='event';field('event-recurrence').value='none';field('event-interval').value='1'}
for(const [name,start,end,last] of [
 ['one-day event','2026-10-24','2026-10-25','2026-10-24'],
 ['multi-day event','2026-10-24','2026-10-27','2026-10-26'],
 ['month boundary','2026-10-31','2026-11-02','2026-11-01'],
 ['leap-day boundary','2028-02-28','2028-03-01','2028-02-29'],
 ['year boundary','2026-12-31','2027-01-02','2027-01-01']]){
 test(name+' displays inclusive last day and saves original interval',()=>{base();api.setDateFields(start,end,true);assert.equal(field('event-end-date').value,last);let saved=api.buildEvent();assert.equal(saved.end,end);assert.equal(api.validateEvent(saved),'');api.setDateFields(saved.start,saved.end,true);assert.equal(api.buildEvent().end,end,'editing must not add a second day')});
}
test('new one-day inclusive input has one-day API duration',()=>{base();field('event-all-day').checked=true;field('event-start-date').value='2026-10-24';field('event-end-date').value='2026-10-24';assert.equal(api.buildEvent().end,'2026-10-25');assert.equal(api.validateEvent(api.buildEvent()),'')});
test('last day before first day fails validation',()=>{base();field('event-all-day').checked=true;field('event-start-date').value='2026-10-24';field('event-end-date').value='2026-10-23';assert.notEqual(api.validateEvent(api.buildEvent()),'')});
test('empty end remains missing rather than becoming an invalid generated date',()=>{base();field('event-all-day').checked=true;field('event-start-date').value='2026-10-24';assert.equal(api.buildEvent().end,'');assert.notEqual(api.validateEvent(api.buildEvent()),'')});
test('timed UTC input remains KST timed and does not get an extra day',()=>{base();api.setDateFields('2026-10-24T01:00:00Z','2026-10-24T02:00:00Z',false);assert.equal(field('event-start-time').value,'10:00');const saved=api.buildEvent();assert.equal(saved.start,'2026-10-24T10:00:00+09:00');assert.equal(saved.end,'2026-10-24T11:00:00+09:00')});
test('recurring series retains interval, anchor and inclusive repeat-until',()=>{base();api.setDateFields('2026-10-24','2026-10-26',true);field('event-recurrence').value='weekly';field('event-interval').value='2';field('event-repeat-until').value='2026-11-30';const saved=api.buildEvent();assert.equal(saved.end,'2026-10-26');assert.equal(saved.recurrence,'weekly');assert.equal(saved.interval,2);assert.equal(saved.repeat_until,'2026-11-30')});
test('editing one recurring occurrence keeps its original one-day interval',()=>{base();api.setEditor({detail:{series:{recurrence:'weekly'}}});field('event-scope').value='occurrence';api.setDateFields('2026-11-07','2026-11-08',true);field('event-recurrence').value='weekly';const saved=api.buildEvent();assert.equal(saved.end,'2026-11-08');assert.equal(saved.recurrence,'none');assert.equal(saved.repeat_until,null)});
test('repeated midnight timed/all-day toggles preserve the original timed interval',()=>{base();api.setDateFields('2026-10-24T09:00:00+09:00','2026-10-26T00:00:00+09:00',false);for(let i=0;i<3;i++){field('event-all-day').checked=true;api.toggleAllDayMode();assert.equal(field('event-end-date').value,'2026-10-25');assert.equal(api.buildEvent().end,'2026-10-26');field('event-all-day').checked=false;api.toggleAllDayMode();assert.equal(api.buildEvent().end,'2026-10-26T00:00:00+09:00')}});
