// Run with Node: verifies component events, draft handoff and HTML escaping.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const handlers={},messages=[],app={innerHTML:''},parent={postMessage:m=>messages.push(m)};
const document={activeElement:null,documentElement:{lang:'en'},body:{classList:{toggle:()=>{}}},getElementById:id=>id==='app'?app:null,addEventListener:()=>{},querySelectorAll:()=>[]};
const context={window:{parent,addEventListener:(name,fn)=>handlers[name]=fn},document,localStorage:{getItem:()=>null,setItem:()=>{}},crypto:{randomUUID:()=>String(messages.length)},requestAnimationFrame:()=>{},setInterval:()=>{},setTimeout:()=>{},devicePixelRatio:1};
vm.createContext(context);vm.runInContext(fs.readFileSync(require('path').join(__dirname,'../ui/app.js'),'utf8'),context);
assert.equal(vm.runInContext('ui.mode',context),'backend');
const doc={id:'a',filename:'00000018.TIF',values:{station:null,line:null,plan_number:null},original_values:{station:null,line:null,plan_number:null},confidence:{station:null,line:null,plan_number:null},manually_changed:{station:false,line:false,plan_number:false},review_status:'unreviewed'};
const job={id:'job',name:'<script>bad</script>',documents:[doc],processing_status:'manual'};
handlers.message({source:parent,data:{type:'streamlit:render',args:{job,jobs:[],selected:'a',preview:null,ack:null,error:null}}});
assert(app.innerHTML.includes('field-station'));
assert(app.innerHTML.includes('field-line'));
assert(app.innerHTML.includes('field-plan_number'));
assert(!app.innerHTML.includes('Ticket Type'));
assert(!app.innerHTML.includes('<script>bad</script>'));
vm.runInContext("editField('station','Friedrichstraße');editField('plan_number','0012');saveReview('reviewed')",context);
const event=messages.at(-1).value;
assert.equal(event.type,'save');assert.equal(event.payload.values.station,'Friedrichstraße');assert.equal(event.payload.values.plan_number,'0012');assert.equal(event.payload.review_status,'reviewed');
// A later keystroke while saving is in flight must not be erased by the acknowledgment.
vm.runInContext("editField('station','New draft')",context);
const updated=JSON.parse(JSON.stringify(job));updated.documents[0].values=event.payload.values;updated.documents[0].review_status='reviewed';
handlers.message({source:parent,data:{type:'streamlit:render',args:{job:updated,jobs:[],selected:'a',preview:null,ack:event.id,error:null}}});
assert.equal(vm.runInContext('values(doc()).station',context),'New draft');
vm.runInContext("send('select',{doc_id:'b'})",context);
assert.equal(messages.at(-1).value.payload.draft.values.station,'New draft');
vm.runInContext("setLanguage('de');toggleDark()",context);
assert.equal(document.documentElement.lang,'de');assert(app.innerHTML.includes('Bahnhofsname'));
console.log('UI event, draft-preservation, translation and escaping checks passed');

vm.runInContext("pending=null;data.logo_url='data:image/png;base64,AA';data.job.number=17;render()",context);
assert(app.innerHTML.includes('alt="BVG"'));
assert(app.innerHTML.includes('J17'));
console.log('Automatic-review default, PNG logo and job-number rendering passed');
