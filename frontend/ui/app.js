/* Plain JavaScript + Streamlit's component message protocol. No frontend build step. */

let data={
 job:null,
 jobs:[],
 selected:null,
 preview:null,
 error:null
};

let ui={
 view:'overview',
 language:'en',
 dark:false,
 filter:'all',
 search:'',
 zoom:1,
 rotation:0,
 help:false,
 export:false,
 scope:'reviewed',
 files:[],
 mode:'backend'
};

let drafts={};
let pending=null;
let downloaded=null;
let notice='';
let noticeTimer=null;
let noticeKey='';
let reading=false;
let uploadProgress='';

try{

 ui.language=
  localStorage.getItem(
   'bvgLanguage'
  )||'en';

 ui.dark=
  localStorage.getItem(
   'bvgDark'
  )==='true';

}catch(_){}

const t=(en,de)=>
 ui.language==='de'
  ?de
  :en;

function hideNotice(){

 if(noticeTimer){

  clearTimeout(
   noticeTimer
  );

  noticeTimer=null;
 }

 const hadError=
  Boolean(
   data.error
  );

 notice='';

 if(hadError){

  noticeKey=
   data.error;

  send(
   'dismiss'
  );

  return;
 }

 noticeKey='';

 render();
}

function armNotice(){

 const text=
  data.error
  ||notice
  ||'';

 if(text===noticeKey){

  return;
 }

 if(noticeTimer){

  clearTimeout(
   noticeTimer
  );

  noticeTimer=null;
 }

 noticeKey=text;

 if(!text){

  return;
 }

 noticeTimer=setTimeout(
  hideNotice,
  10000
 );
}

function showNotice(text){

 notice=text;

 noticeKey='';

 if(noticeTimer){

  clearTimeout(
   noticeTimer
  );

  noticeTimer=null;
 }
}

const esc=value=>
 String(
  value??''
 )
 .replace(
  /[&<>"']/g,
  c=>({
   '&':'&amp;',
   '<':'&lt;',
   '>':'&gt;',
   '"':'&quot;',
   "'":'&#39;'
  }[c])
 );

const fields=[
 'station',
 'line',
 'plan_number'
];

const labels=()=>({
 station:
  t(
   'Station name',
   'Bahnhofsname'
  ),
 line:
  t(
   'Line',
   'Linie'
  ),
 plan_number:
  t(
   'Plan number',
   'Plannummer'
  )
});

const jobLabel=j=>
 j
  ?`J${j.number||'…'}`
  :'';

const createdLabel=j=>
 j?.created_at
  ?new Intl.DateTimeFormat(
    ui.language==='de'
     ?'de-DE'
     :'en-GB',
    {
     dateStyle:'medium',
     timeStyle:'short'
    }
   ).format(
    new Date(
     j.created_at
    )
   )
  :'';

const doc=()=>
 data.job?.documents.find(
  d=>d.id===data.selected
 );

const values=d=>
 drafts[d.id]
 ||d.values;

const dirty=d=>
 !!d
 &&!!drafts[d.id]
 &&JSON.stringify(
  drafts[d.id]
 )!==JSON.stringify(
  d.values
 );

const draft=()=>
 dirty(doc())
  ?{
    doc_id:doc().id,
    values:{
     ...values(doc())
    }
   }
  :null;

const busy=()=>
 !!pending
 ||reading;

const disabled=condition=>
 condition
  ?'disabled'
  :'';

const statusLabel=d=>
 d.review_status==='reviewed'
  ?t(
    'Reviewed',
    'Geprüft'
   )
  :d.review_status==='unresolved'
   ?t(
     'Unresolved',
     'Ungeklärt'
    )
   :t(
     'Needs review',
     'Prüfbedarf'
    );

function post(
 type,
 extra={}
){

 window.parent.postMessage(
  {
   isStreamlitMessage:true,
   type,
   ...extra
  },
  '*'
 );
}

function send(
 type,
 payload={},
 nextView=null
){

 if(pending){

  showNotice(t(
   'Please wait for the current action.',
   'Bitte warten Sie auf den aktuellen Vorgang.'
  ));

  render();

  return;
 }

 const current=
  draft();

 if(
  current
  &&!payload.draft
  &&![
   'create',
   'open',
   'delete_job',
   'poll',
   'begin_upload',
   'upload_chunk',
   'finish_upload',
   'stop_upload'
  ].includes(type)
 ){

  payload.draft=
   current;
 }

 const id=
  crypto.randomUUID
   ?crypto.randomUUID()
   :Date.now()
    +'-'
    +Math.random();

 pending={
  id,
  type,
  payload,
  nextView,
  draft:
   payload.draft
   ||(
    type==='save'
     ?{
       doc_id:
        payload.doc_id,
       values:
        payload.values
      }
     :null
   )
 };

 post(
  'streamlit:setComponentValue',
  {
   value:{
    id,
    type,
    payload
   },
   dataType:'json'
  }
 );

 render();
}

function sendAsync(
 type,
 payload={},
 nextView=null
){

 return new Promise(
  (
   resolve,
   reject
  )=>{

   if(pending){

    reject(
     new Error(
      'An action is already running.'
     )
    );

    return;
   }

   send(
    type,
    payload,
    nextView
   );

   pending.resolve=
    resolve;

   pending.reject=
    reject;
  }
 );
}

window.addEventListener(
 'message',
 event=>{

  if(
   event.source
   !==window.parent
   ||event.data.type
   !=='streamlit:render'
  ){
   return;
  }

  const next=
   event.data.args;

  let completed=null;

  const changedJob=
   next.job?.id
   !==data.job?.id;

  const changedDoc=
   next.selected
   !==data.selected
   ||next.preview?.page
   !==data.preview?.page;

  if(
   pending
   &&next.ack
   ===pending.id
  ){

   if(
    !next.error
   ){

    const d=
     pending.draft;

    if(
     d
     &&JSON.stringify(
      drafts[
       d.doc_id
      ]
     )
     ===JSON.stringify(
      d.values
     )
    ){

     delete drafts[
      d.doc_id
     ];
    }

    if(
     pending.nextView
    ){

     ui.view=
      pending.nextView;
    }

    if(
     pending.openExport
    ){

     ui.export=true;
    }

    if(
     pending.type
     ==='save'
    ){

     showNotice(t(
      'Changes saved locally.',
      'Änderungen lokal gespeichert.'
     ));
    }

    if(
     pending.type
     ==='create'
    ){

     ui.files=[];
    }

    if(
     pending.type
     ==='delete_job'
    ){

     showNotice(t(
      'Job deleted.',
      'Auftrag gelöscht.'
     ));
    }
   }

   completed=
    pending;

   pending=
    null;
  }

  if(
   changedJob
  ){

   drafts={};

   ui.view=
    next.job
     ?(
       next.job.processing_status
       ==='uploading'
        ?'upload'
        :'review'
      )
     :'overview';

   ui.filter=
    'all';

   ui.search=
    '';
  }

  if(
   changedDoc
  ){

   ui.zoom=
    1;

   ui.rotation=
    0;
  }

  data=
   next;

  if(
   data.download
   &&downloaded
   !==data.download.id
  ){

   downloaded=
    data.download.id;

   downloadFile(
    data.download
   );
  }

  render();

  if(
   completed
  ){

   if(
    next.error
   ){

    completed.reject?.(
     new Error(
      next.error
     )
    );

   }else{

    completed.resolve?.(
     next
    );
   }
  }
 }
);

function downloadFile(
 file
){

 const raw=
  atob(
   file.data
  );

 const bytes=
  Uint8Array.from(
   raw,
   c=>
    c.charCodeAt(0)
  );

 const url=
  URL.createObjectURL(
   new Blob(
    [bytes],
    {
     type:file.mime
    }
   )
  );

 const a=
  document.createElement(
   'a'
  );

 a.href=
  url;

 a.download=
  file.filename;

 document.body.append(
  a
 );

 a.click();

 a.remove();

 setTimeout(
  ()=>{
   URL.revokeObjectURL(
    url
   );
  },
  30000
 );
}

function changeView(
 view
){

 if(
  dirty(
   doc()
  )
 ){

  const d=
   doc();

  send(
   'save',
   {
    doc_id:
     d.id,

    values:
     values(d)
   },
   view
  );

 }else{

  ui.view=
   view;

  render();
 }
}

function openJob(
 id
){

 if(
  dirty(
   doc()
  )
 ){

  showNotice(t(
   'Save your changes before opening another job.',
   'Speichern Sie Änderungen vor dem Öffnen eines anderen Auftrags.'
  ));

  render();

  return;
 }

 send(
  'open',
  {
   job_id:id
  },
  'review'
 );
}

function deleteJob(
 id
){

 if(
  busy()
 ){
  return;
 }

 if(
  dirty(
   doc()
  )
 ){

  showNotice(t(
   'Save your changes before deleting a job.',
   'Speichern Sie Ihre Änderungen, bevor Sie einen Auftrag löschen.'
  ));

  render();

  return;
 }

 const confirmed=
  window.confirm(
   t(
    'Delete this job permanently?\n\nThe locally stored documents and review data will also be deleted.',
    'Diesen Auftrag wirklich endgültig löschen?\n\nDie lokal gespeicherten Dokumente und Prüfdaten werden ebenfalls gelöscht.'
   )
  );

 if(
  !confirmed
 ){
  return;
 }

 send(
  'delete_job',
  {
   job_id:id
  }
 );
}

function selectDoc(
 id
){

 send(
  'select',
  {
   doc_id:id
  }
 );
}

function acceptStationSuggestion(){

 const d=
  doc();

 if(
  !d
  ||!d.station_suggestion
 ){

  return;
 }

 delete drafts[d.id];

 send(
  'station_suggestion',
  {
   doc_id:d.id,
   decision:'accept'
  }
 );
}

function dismissStationSuggestion(){

 const d=
  doc();

 if(
  !d
  ||!d.station_suggestion
 ){

  return;
 }

 delete drafts[d.id];

 send(
  'station_suggestion',
  {
   doc_id:d.id,
   decision:'dismiss'
  }
 );
}

function stationSuggestionBox(
 d
){

 const suggestion=
  d.station_suggestion;

 if(
  !suggestion
  ||!suggestion.name
  ||(values(d).station||'')===suggestion.name
 ){

  return '';
 }

 return `
  <div class="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">

   <p class="text-xs text-amber-950">

    ${
     t(
      'Possible station from the BVG list',
      'Möglicher Stationsname aus der BVG-Liste'
     )
    }:

    <span class="font-semibold">

     ${
      esc(
       suggestion.name
      )
     }

    </span>

   </p>

   ${
    suggestion.read_text
     ?`
      <p class="text-xs text-gray-600 mt-1">

       ${
        t(
         'Read by OCR',
         'Gelesen'
        )
       }:

       ${
        esc(
         suggestion.read_text
        )
       }

      </p>
     `
     :''
   }

   <div class="flex gap-2 mt-2">

    <button
     type="button"
     ${
      disabled(
       busy()
      )
     }
     onclick="acceptStationSuggestion()"
     class="px-3 py-1.5 text-xs font-semibold rounded-md bg-[#f5c400]"
    >

     ${
      t(
       'Accept',
       'Übernehmen'
      )
     }

    </button>

    <button
     type="button"
     ${
      disabled(
       busy()
      )
     }
     onclick="dismissStationSuggestion()"
     class="px-3 py-1.5 text-xs rounded-md border border-gray-300 bg-white"
    >

     ${
      t(
       'Dismiss',
       'Ablehnen'
      )
     }

    </button>

   </div>

  </div>
 `;
}

function editField(
 key,
 value
){

 const d=
  doc();

 drafts[
  d.id
 ]={
  ...values(d),
  [key]:
   value
 };

 const el=
  document.getElementById(
   'save-state'
  );

 if(
  el
 ){

  el.textContent=
   t(
    'Unsaved changes',
    'Ungespeicherte Änderungen'
   );
 }
}

function saveReview(
 status
){

 const d=
  doc();

 if(
  d
 ){

  send(
   'save',
   {
    doc_id:
     d.id,

    values:{
     ...values(d)
    },

    review_status:
     status
   }
  );
 }
}

function setLanguage(
 value
){

 ui.language=
  value;

 try{

  localStorage.setItem(
   'bvgLanguage',
   value
  );

 }catch(_){}

 render();
}

function toggleDark(){

 ui.dark=
  !ui.dark;

 try{

  localStorage.setItem(
   'bvgDark',
   String(
    ui.dark
   )
  );

 }catch(_){}

 render();
}

function statusIcon(
 d
){

 return d.review_status
 ==='reviewed'
  ?`
   <span class="w-5 h-5 rounded-full bg-emerald-100 text-emerald-700 flex items-center justify-center text-xs">
    ✓
   </span>
  `
  :d.review_status
   ==='unresolved'
   ?`
    <span class="w-5 h-5 rounded-full bg-red-100 text-red-700 flex items-center justify-center text-xs">
     ?
    </span>
   `
   :`
    <span class="w-5 h-5 rounded-full bg-amber-100 text-amber-700 flex items-center justify-center text-xs">
     !
    </span>
   `;
}

function preferences(){

 return `
 <div class="flex items-center gap-2">

  <select
   aria-label="Language / Sprache"
   onchange="setLanguage(this.value)"
   class="ui-control lang-select border rounded-lg py-2 text-xs"
  >

   <option
    value="en"
    ${
     ui.language==='en'
      ?'selected'
      :''
    }
   >
    English
   </option>

   <option
    value="de"
    ${
     ui.language==='de'
      ?'selected'
      :''
    }
   >
    Deutsch
   </option>

  </select>

  <button
   aria-label="${
    t(
     'Toggle dark mode',
     'Farbschema wechseln'
    )
   }"
   onclick="toggleDark()"
   class="ui-control px-3 py-2 border rounded-lg"
  >

   ${
    ui.dark
     ?'☀'
     :'☾'
   }

  </button>

 </div>
 `;
}

function nav(){

 return `
 <aside class="w-64 bg-white border-r border-gray-200 h-screen flex flex-col shrink-0">

  <div class="px-6 py-5 border-b border-gray-100">

   <div class="flex items-center gap-3">

    ${
     data.logo_url
      ?`
       <img
        src="${esc(data.logo_url)}"
        alt="BVG"
        style="width:64px;height:auto;max-height:48px;object-fit:contain"
       >
      `
      :''
    }

    <div>

     <div class="font-bold">

      ${
       t(
        'Plan Archive',
        'Planarchiv'
       )
      }

     </div>

     <div class="text-xs text-gray-500">

      ${
       t(
        'Construction plans',
        'Baupläne'
       )
      }

     </div>

    </div>

   </div>

  </div>

  <nav class="p-3 space-y-1 text-sm">

   ${
    [
     [
      'overview',
      '⌂',
      t(
       'Overview',
       'Übersicht'
      )
     ],

     [
      'upload',
      '＋',
      t(
       'New job',
       'Neuer Auftrag'
      )
     ],

     [
      'review',
      '□',
      t(
       'Review',
       'Prüfung'
      )
     ]
    ]
    .map(
     (
      [
       page,
       icon,
       label
      ]
     )=>`

      <button
       ${
        disabled(
         busy()
        )
       }
       onclick="changeView('${page}')"
       class="w-full text-left px-4 py-2.5 rounded-lg flex items-center gap-3 ${
        ui.view===page
         ?'bg-[#fff7c9] font-semibold'
         :''
       }"
      >

       <span class="text-gray-500">
        ${icon}
       </span>

       ${label}

      </button>

     `
    )
    .join('')
   }

  </nav>

  <div class="mt-auto p-4 space-y-2 border-t border-gray-100 text-sm">

   <button
    onclick="ui.help=true;render()"
    class="w-full text-left px-3 py-2 text-gray-600"
   >

    ?
    ${
     t(
      'Help',
      'Hilfe'
     )
    }

   </button>

   <div class="px-3 pt-2">

    <div class="font-medium">

     ${
      t(
       'Local workspace',
       'Lokaler Arbeitsbereich'
      )
     }

    </div>

    <div class="text-xs text-gray-500">

     ${
      t(
       'Student prototype',
       'Studienprototyp'
      )
     }

    </div>

   </div>

  </div>

 </aside>
 `;
}

function header(){

 const processing=
  data.job
   ?.processing_status
  ==='processing';

 return `
 <header class="h-16 bg-white border-b border-gray-200 flex items-center justify-between px-7 shrink-0">

  <div class="min-w-0">

   <div class="text-sm font-semibold truncate">

    ${
     esc(
      data.job
       ?jobLabel(
         data.job
        )
       :t(
         'Plan workspace',
         'Plan-Arbeitsbereich'
        )
     )
    }

   </div>

   <div class="text-xs text-gray-500">

    ${
     data.job
      ?data.job.documents.length
       +' '
       +t(
        'documents',
        'Dokumente'
       )
      :t(
        'Upload · Review · Export',
        'Hochladen · Prüfen · Exportieren'
       )
    }

   </div>

  </div>

  <div class="flex items-center gap-4 text-xs text-gray-500">

   ${preferences()}

   <span class="shrink-0 whitespace-nowrap">

    ${
     busy()
      ?t(
        'Saving / loading…',
        'Speichern / Laden…'
       )
      :processing
       ?t(
         'Processing…',
         'Verarbeitung…'
        )
       :t(
         'Local workspace',
         'Lokaler Arbeitsbereich'
        )
    }

   </span>

   <button
    onclick="ui.help=true;render()"
    class="px-3 py-2 border rounded-lg hover:bg-gray-50"
   >

    ${
     t(
      'Help',
      'Hilfe'
     )
    }

   </button>

  </div>

 </header>
 `;
}

/* =========================================================
   PIPELINE-SCHRITTE
   ========================================================= */

function steps(){

 return `
 <div class="h-12 bg-white border-b flex items-center px-5 gap-8 text-xs">

  <button
   onclick="changeView('upload')"
   class="font-medium"
  >

   ${
    t(
     'Step 1: Files',
     '1. Schritt: Dateien'
    )
   }

  </button>

  <span class="text-gray-500 font-medium">

   ${
    t(
     'Step 2: Processing',
     '2. Schritt: Verarbeitung'
    )
   }

  </span>

  <span class="font-semibold border-b-2 border-[#f5c400] h-full flex items-center">

   ${
    t(
     'Step 3: Review',
     '3. Schritt: Prüfung'
    )
   }

  </span>

  <button
   onclick="openExport()"
   class="font-medium"
  >

   ${
    t(
     'Step 4: Export',
     '4. Schritt: Export'
    )
   }

  </button>

 </div>
 `;
}

function filtered(){

 return (
  data.job?.documents
  ||[]
 )
 .filter(
  d=>
   (
    ui.filter==='all'
    ||d.review_status===ui.filter
   )
   &&
   [
    d.filename,
    ...Object.values(
     d.values
    )
   ]
   .join(' ')
   .toLowerCase()
   .includes(
    ui.search
     .toLowerCase()
   )
 );
}

function documentList(){

 const docs=
  filtered();

 const all=
  data.job.documents;

 return `
 <aside class="w-56 bg-white border-r border-gray-200 flex flex-col shrink-0">

  <div class="p-4 border-b">

   <div class="font-semibold text-sm">

    ${
     t(
      'Documents',
      'Dokumente'
     )
    }

   </div>

   <div class="text-xs text-gray-500 mt-1">

    ${all.length}

    ${
     t(
      'total',
      'insgesamt'
     )
    }

   </div>

  </div>

  <div class="p-3 space-y-1 border-b text-xs">

   ${
    [
     [
      'all',
      t(
       'All',
       'Alle'
      ),
      all.length
     ],

     [
      'unreviewed',
      t(
       'Needs review',
       'Prüfbedarf'
      ),
      all.filter(
       d=>
        d.review_status
        ==='unreviewed'
      ).length
     ],

     [
      'reviewed',
      t(
       'Reviewed',
       'Geprüft'
      ),
      all.filter(
       d=>
        d.review_status
        ==='reviewed'
      ).length
     ],

     [
      'unresolved',
      t(
       'Unresolved',
       'Ungeklärt'
      ),
      all.filter(
       d=>
        d.review_status
        ==='unresolved'
      ).length
     ]
    ]
    .map(
     (
      [
       key,
       label,
       count
      ]
     )=>`

      <button
       onclick="ui.filter='${key}';render()"
       class="w-full flex justify-between px-3 py-2 rounded ${
        ui.filter===key
         ?'bg-gray-100 font-medium'
         :''
       }"
      >

       <span>
        ${label}
       </span>

       <span>
        ${count}
       </span>

      </button>

     `
    )
    .join('')
   }

   <input
    aria-label="${
     t(
      'Search documents',
      'Dokumente suchen'
     )
    }"
    placeholder="${
     t(
      'Search documents…',
      'Dokumente suchen…'
     )
    }"
    value="${
     esc(
      ui.search
     )
    }"
    oninput="ui.search=this.value;render(true)"
    class="w-full border rounded px-2 py-2"
   >

  </div>

  <div class="flex-1 overflow-y-auto scrollbar p-2">

   ${
    docs
    .map(
     d=>`

      <button
       ${
        disabled(
         busy()
        )
       }
       onclick="selectDoc('${d.id}')"
       class="w-full flex items-center gap-2 p-2 rounded-lg ${
        d.id===data.selected
         ?'bg-[#fff7c9]'
         :''
       } hover:bg-gray-50 mb-1"
      >

       <div class="w-10 h-12 rounded bg-gray-100 border flex items-center justify-center text-[9px] text-gray-400">

        ${
         esc(
          d.filename
           .split('.')
           .pop()
           .toUpperCase()
         )
        }

       </div>

       <div class="min-w-0 text-left flex-1">

        <div
         class="text-xs font-medium truncate"
         title="${
          esc(
           d.filename
          )
         }"
        >

         ${
          esc(
           d.filename
          )
         }

        </div>

        <div class="text-[10px] text-gray-500 mt-1">

         ${
          statusLabel(
           d
          )
         }

        </div>

       </div>

       ${
        statusIcon(
         d
        )
       }

      </button>

     `
    )
    .join('')
    ||
    `
     <p class="p-3 text-xs text-gray-500">

      ${
       t(
        'No matching documents.',
        'Keine passenden Dokumente.'
       )
      }

     </p>
    `
   }

  </div>

  <div class="p-3 border-t flex items-center justify-between text-xs text-gray-500">

   <span>

    ${
     all.findIndex(
      d=>
       d.id
       ===data.selected
     )+1
    }

    /

    ${all.length}

   </span>

   <div class="flex gap-1">

    <button
     ${
      disabled(
       busy()
      )
     }
     onclick="moveDoc(-1)"
     class="px-2 py-1 border rounded"
    >
     ←
    </button>

    <button
     ${
      disabled(
       busy()
      )
     }
     onclick="moveDoc(1)"
     class="px-2 py-1 border rounded"
    >
     →
    </button>

   </div>

  </div>

 </aside>
 `;
}

function moveDoc(
 delta
){

 const a=
  filtered();

 const i=
  a.findIndex(
   d=>
    d.id
    ===data.selected
  );

 const next=
  a[
   i+delta
  ];

 if(
  next
 ){

  selectDoc(
   next.id
  );
 }
}

function viewer(){

 return `
 <div class="flex-1 min-w-0 bg-[#eef0f2] relative overflow-hidden flex flex-col">

  <div class="h-12 bg-white border-b border-gray-200 flex items-center justify-between px-4">

   <div class="text-xs text-gray-500 truncate">

    ${
     esc(
      doc()?.filename
     )
    }

   </div>

   <div class="flex gap-1">

    <button
     title="${
      t(
       'Zoom out',
       'Verkleinern'
      )
     }"
     onclick="zoom(-.25)"
     class="p-2 rounded hover:bg-gray-100"
    >
     −
    </button>

    <button
     title="${
      t(
       'Fit page',
       'Seite einpassen'
      )
     }"
     onclick="ui.zoom=1;ui.rotation=0;drawPreview()"
     class="px-2 text-xs"
    >

     ${
      Math.round(
       ui.zoom
       *100
      )
     }%

    </button>

    <button
     title="${
      t(
       'Zoom in',
       'Vergrößern'
      )
     }"
     onclick="zoom(.25)"
     class="p-2 rounded hover:bg-gray-100"
    >
     ＋
    </button>

    <span class="w-px bg-gray-200 mx-1">
    </span>

    <button
     title="${
      t(
       'Rotate',
       'Drehen'
      )
     }"
     onclick="ui.rotation=(ui.rotation+90)%360;drawPreview()"
     class="p-2 rounded hover:bg-gray-100"
    >
     ↻
    </button>

    <button
     title="${
      t(
       'Fullscreen',
       'Vollbild'
      )
     }"
     onclick="fullscreen()"
     class="p-2 rounded hover:bg-gray-100"
    >
     ⛶
    </button>

   </div>

  </div>

  <div
   id="image-stage"
   class="flex-1 overflow-auto scrollbar p-8"
   style="background:inherit"
  >

   <canvas
    id="scan-canvas"
    class="mx-auto"
   >
   </canvas>

   ${
    data.preview
     ?''
     :`
      <p class="text-sm text-gray-500">

       ${
        esc(
         data.preview_error
         ||t(
          'Loading preview…',
          'Vorschau wird geladen…'
         )
        )
       }

      </p>
     `
   }

  </div>

  <div class="bg-white border-t px-4 py-2 flex items-center justify-between text-xs text-gray-500">

   <span>

    ${
     t(
      'Page',
      'Seite'
     )
    }

    ${
     (
      data.preview?.page
      ||0
     )+1
    }

    /

    ${
     data.preview?.pages
     ||1
    }

   </span>

   <div class="flex gap-2">

    <button
     ${
      disabled(
       busy()
       ||!data.preview
       ||data.preview.page===0
      )
     }
     onclick="send('page',{page:data.preview.page-1})"
    >
     ←
    </button>

    <button
     ${
      disabled(
       busy()
       ||!data.preview
       ||data.preview.page+1
       >=data.preview.pages
      )
     }
     onclick="send('page',{page:data.preview.page+1})"
    >
     →
    </button>

   </div>

  </div>

 </div>
 `;
}

function zoom(
 delta
){

 ui.zoom=
  Math.max(
   .25,
   Math.min(
    15,
    ui.zoom
    +delta
   )
  );

 render();
}

function drawPreview(){

 const canvas=
  document.getElementById(
   'scan-canvas'
  );

 const stage=
  document.getElementById(
   'image-stage'
  );

 if(
  !canvas
  ||!data.preview
 ){
  return;
 }

 const image=
  new Image();

 image.onload=()=>{

  if(
   !canvas.isConnected
  ){
   return;
  }

  const rotated=
   ui.rotation
   %180
   !==0;

  const w=
   rotated
    ?image.height
    :image.width;

  const h=
   rotated
    ?image.width
    :image.height;

  const fit=
   Math.min(
    (
     stage.clientWidth
     -64
    )/w,
    (
     stage.clientHeight
     -64
    )/h
   );

  const scale=
   Math.max(
    .05,
    fit
   )
   *ui.zoom;

  const ratio=
   Math.min(
    devicePixelRatio
    ||1,
    2
   );

  canvas.width=
   Math.round(
    w
    *scale
    *ratio
   );

  canvas.height=
   Math.round(
    h
    *scale
    *ratio
   );

  canvas.style.width=
   w
   *scale
   +'px';

  canvas.style.height=
   h
   *scale
   +'px';

  const ctx=
   canvas.getContext(
    '2d'
   );

  ctx.scale(
   ratio,
   ratio
  );

  ctx.translate(
   w
   *scale
   /2,
   h
   *scale
   /2
  );

  ctx.rotate(
   ui.rotation
   *Math.PI
   /180
  );

  ctx.drawImage(
   image,
   -image.width
   *scale
   /2,
   -image.height
   *scale
   /2,
   image.width
   *scale,
   image.height
   *scale
  );
 };

 image.src=
  data.preview.url;
}

function fullscreen(){

 const stage=
  document.getElementById(
   'image-stage'
  );

 if(
  document.fullscreenElement
 ){

  document.exitFullscreen();

 }else if(
  stage.requestFullscreen
 ){

  stage
   .requestFullscreen()
   .catch(
    ()=>{

     showNotice(t(
      'Fullscreen is unavailable in this browser. Zoom and scrolling still work.',
      'Vollbild ist in diesem Browser nicht verfügbar. Zoom und Scrollen funktionieren weiterhin.'
     ));

     render();
    }
   );
 }
}

document.addEventListener(
 'fullscreenchange',
 ()=>{
  setTimeout(
   drawPreview,
   50
  );
 }
);

window.addEventListener(
 'resize',
 drawPreview
);

function rightPanel(){

 const d=
  doc();

 const v=
  values(
   d
  );

 return `
 <section class="w-[390px] bg-white border-l border-gray-200 flex flex-col shrink-0">

  <div class="px-5 py-4 border-b border-gray-200 flex items-center justify-between">

   <div>

    <div class="font-semibold">

     ${
      t(
       'Extracted data',
       'Extrahierte Daten'
      )
     }

    </div>

    <div class="text-xs text-gray-500 mt-0.5">

     ${
      t(
       'Station · Line · Plan number',
       'Bahnhof · Linie · Plannummer'
      )
     }

    </div>

   </div>

   <span class="text-xs px-2.5 py-1.5 rounded-md bg-amber-50 text-amber-800">

    3
    ${
     t(
      'fields',
      'Felder'
     )
    }

   </span>

  </div>

  <div class="px-5 py-3 bg-gray-50 border-b text-xs flex items-center justify-between">

   <span>

    ${
     statusLabel(
      d
     )
    }

   </span>

   <span
    id="save-state"
    class="dirty"
   >

    ${
     dirty(
      d
     )
      ?t(
        'Unsaved changes',
        'Ungespeicherte Änderungen'
       )
      :t(
        'Saved locally',
        'Lokal gespeichert'
       )
    }

   </span>

  </div>

  <div class="flex-1 overflow-y-auto scrollbar p-5 space-y-4">

   ${
    fields
    .map(
     key=>`

      <div>

       <div class="flex items-center justify-between mb-1.5">

        <label
         for="field-${key}"
         class="text-xs font-medium text-gray-700"
        >

         ${
          labels()[key]
         }

        </label>

        <span class="text-[10px] text-gray-500">

         ${
          d.manually_changed[
           key
          ]

           ?t(
             'Manually changed',
             'Manuell geändert'
            )

           :v[
             key
            ]

            ?t(
              'Value found',
              'Wert gefunden'
             )

            :t(
              'Not found',
              'Nicht gefunden'
             )
         }

        </span>

       </div>

       <input
        id="field-${key}"
        maxlength="1000"
        value="${
         esc(
          v[
           key
          ]
         )
        }"
        placeholder="${
         t(
          'Enter a value or leave blank',
          'Wert eingeben oder leer lassen'
         )
        }"
        oninput="editField('${key}',this.value)"
        class="field-input w-full px-3 py-2.5 text-sm border ${
         !v[
          key
         ]
          ?'border-amber-300 bg-amber-50/30'
          :'border-gray-200'
        } rounded-lg"
       >

       ${
        d.manually_changed[
         key
        ]
         ?`
          <p class="text-xs text-gray-500 mt-1">

           ${
            t(
             'Originally found',
             'Ursprünglich gefunden'
            )
           }:

           ${
            esc(
             d.original_values[
              key
             ]
             ||'—'
            )
           }

          </p>
         `
         :''
       }

       ${
        key==='station'
         ?stationSuggestionBox(
           d
          )
         :''
       }

      </div>

     `
    )
    .join('')
   }

   <p class="text-xs text-gray-500">

    ${
     t(
      'Leave information blank if it is absent or unreadable. Confirming records the review, even if a field remains empty.',
      'Fehlende oder unlesbare Angaben leer lassen. Bestätigen dokumentiert die Prüfung auch bei leeren Feldern.'
     )
    }

   </p>

   ${
    d.evidence
     ?`
      <div class="border-t pt-4">

       <div class="text-xs font-semibold">

        ${
         t(
          'Supporting OCR text',
          'OCR-Belegtext'
         )
        }

       </div>

       <p
        class="text-xs text-gray-600 mt-2"
        style="white-space:pre-wrap;overflow-wrap:anywhere"
       >

        ${
         esc(
          typeof d.evidence==='string'
           ?d.evidence
           :JSON.stringify(
             d.evidence,
             null,
             2
            )
         )
        }

       </p>

      </div>
     `
     :''
   }

   ${
    d.bbox
     ?`
      <div class="text-xs text-gray-500">

       ${
        t(
         'Source coordinates',
         'Quellkoordinaten'
        )
       }:

       ${
        esc(
         JSON.stringify(
          d.bbox
         )
        )
       }

      </div>
     `
     :''
   }

   ${
    d.processing_error
     ?`
      <p class="text-xs text-red-600">

       ${
        esc(
         d.processing_error
        )
       }

      </p>
     `
     :''
   }

  </div>

  <div class="p-4 border-t bg-white space-y-2">

   <button
    ${
     disabled(
      busy()
     )
    }
    onclick="saveReview('reviewed')"
    class="w-full bg-[#f5c400] hover:bg-[#e5b800] text-gray-900 font-semibold py-3 rounded-lg"
   >

    ${
     t(
      'Confirm document',
      'Dokument bestätigen'
     )
    }

    <span class="font-normal text-xs ml-1">
     Ctrl+Enter
    </span>

   </button>

   <div class="flex gap-2">

    <button
     ${
      disabled(
       busy()
      )
     }
     onclick="saveReview()"
     class="flex-1 py-2.5 text-sm border border-gray-200 rounded-lg"
    >

     ${
      t(
       'Save changes',
       'Änderungen speichern'
      )
     }

    </button>

    <button
     ${
      disabled(
       busy()
      )
     }
     onclick="saveReview('unresolved')"
     class="flex-1 py-2.5 text-sm border border-gray-200 rounded-lg"
    >

     ${
      t(
       'Unresolved',
       'Ungeklärt'
      )
     }

    </button>

   </div>

   <button
    onclick="openExport()"
    class="w-full py-2 text-sm text-gray-600"
   >

    ${
     t(
      'Export results →',
      'Ergebnisse exportieren →'
     )
    }

   </button>

  </div>

 </section>
 `;
}

function processingBar(){

 if(
  !data.job
 ){
  return '';
 }

 const status=
  data.job
   .processing_status;

 if(
  status==='processing'
 ){

  return `
   <div class="px-5 py-2 bg-amber-50 text-amber-800 text-xs">

    ${
     t(
      'Backend processing',
      'Backend-Verarbeitung'
     )
    }:

    ${
     data.job.progress?.processed
     ||0
    }

    /

    ${
     data.job.documents.length
    }

   </div>
  `;
 }

 if(
  status==='connection_error'
 ){

  return `
   <div class="px-5 py-2 bg-amber-50 text-amber-800 text-xs">

    ${
     t(
      'Backend connection interrupted. Your job and edits are saved.',
      'Backend-Verbindung unterbrochen. Auftrag und Änderungen sind gespeichert.'
     )
    }

    <button
     onclick="send('resume')"
    >
     ${
      t(
       'Retry status check',
       'Status erneut abfragen'
      )
     }
    </button>

   </div>
  `;
 }

 if(
  [
   'failed',
   'error',
   'cancelled'
  ].includes(
   status
  )
 ){

  return `
   <div class="px-5 py-2 bg-red-100 text-red-700 text-xs">

    ${
     esc(
      data.job.backend_error
      ||status
     )
    }

   </div>
  `;
 }

 return '';
}

function review(){

 if(
  !data.job
  ||!data.job.documents.length
 ){

  return `
   <div class="h-full flex flex-col">

    ${header()}

    <main class="p-8">

     <p>

      ${
       t(
        'Create or open a job to review documents.',
        'Erstellen oder öffnen Sie einen Auftrag zur Dokumentprüfung.'
       )
      }

     </p>

     <button
      onclick="changeView('upload')"
      class="mt-5 bg-bvg px-4 py-2 rounded-lg"
     >

      ${
       t(
        'New job',
        'Neuer Auftrag'
       )
      }

     </button>

    </main>

   </div>
  `;
 }

 return `
  <div class="h-full flex flex-col">

   ${header()}

   ${steps()}

   ${processingBar()}

   <main class="flex-1 flex min-h-0">

    ${documentList()}

    ${viewer()}

    ${rightPanel()}

   </main>

  </div>
 `;
}

/* =========================================================
   ÜBERSICHT
   ========================================================= */

function jobActivity(
 j
){

 const status=
  j.processing_status;

 const done=
  Number(
   j.processed
  )||0;

 const total=
  j.total||0;

 if(
  status==='processing'
 ){

  return {
   kind:'run',

   text:
    total
     ?t(
       'Processing, '
       +done
       +' of '
       +total,

       'Wird verarbeitet, '
       +done
       +' von '
       +total
      )
     :t(
       'Processing…',
       'Wird verarbeitet…'
      )
  };
 }

 if(
  status==='uploading'
 ){

  return {
   kind:'run',

   text:t(
    'Uploading…',
    'Wird hochgeladen…'
   )
  };
 }

 if(
  status==='connection_error'
 ){

  return {
   kind:'warn',

   text:t(
    'Connection interrupted',
    'Verbindung unterbrochen'
   )
  };
 }

 if(
  status==='failed'
  ||status==='error'
  ||status==='cancelled'
 ){

  return {
   kind:'warn',

   text:t(
    'Processing failed',
    'Verarbeitung fehlgeschlagen'
   )
  };
 }

 return null;
}

function dashboard(){

 const jobs=
  data.jobs
  ||[];

 const total=
  jobs.reduce(
   (
    n,
    j
   )=>
    n+j.total,
   0
  );

 const reviewed=
  jobs.reduce(
   (
    n,
    j
   )=>
    n+j.reviewed,
   0
  );

 return `
 <div class="h-full flex flex-col">

  ${header()}

  <main class="p-8 overflow-auto">

   <div class="flex items-end justify-between mb-7">

    <div>

     <h1 class="text-2xl font-bold">

      ${
       t(
        'Overview',
        'Übersicht'
       )
      }

     </h1>

     <p class="text-sm text-gray-500 mt-1">

      ${
       t(
        'Saved on this computer.',
        'Auf diesem Computer gespeichert.'
       )
      }

     </p>

    </div>

    <button
     onclick="changeView('upload')"
     class="bg-[#f5c400] font-semibold px-4 py-2.5 rounded-lg"
    >

     +
     ${
      t(
       'Create new job',
       'Neuen Auftrag erstellen'
      )
     }

    </button>

   </div>

   <div class="grid grid-cols-2 gap-4 mb-7">

    <div class="bg-white border rounded-xl p-5">

     <div class="text-xs text-gray-500">

      ${
       t(
        'Total documents',
        'Dokumente insgesamt'
       )
      }

     </div>

     <div class="text-2xl font-bold mt-2">

      ${total}

     </div>

    </div>

    <div class="bg-white border rounded-xl p-5">

     <div class="text-xs text-gray-500">

      ${
       t(
        'Reviewed documents',
        'Geprüfte Dokumente'
       )
      }

     </div>

     <div class="text-2xl font-bold mt-2">

      ${reviewed}

     </div>

    </div>

   </div>

   <div class="bg-white border rounded-xl">

    <div class="p-5 border-b font-semibold">

     ${
      t(
       'Jobs',
       'Aufträge'
      )
     }

    </div>

    <div class="divide-y">

     ${
      jobs
      .map(
       j=>`

        <div class="p-5 flex items-center gap-5">

         <div class="w-52 shrink-0">

          <div class="font-medium text-sm">

           ${
            esc(
             jobLabel(
              j
             )
            )
           }

          </div>

          ${
           jobActivity(j)
            ?`
             <div class="text-xs mt-1 ${
              jobActivity(j).kind==='run'
               ?'text-amber-700'
               :'text-red-600'
             }">
              ${
               esc(
                jobActivity(j).text
               )
              }
             </div>
            `
            :''
          }

          <div
           class="text-xs text-gray-500 mt-1"
           title="${
            esc(
             j.created_at
             ||''
            )
           }"
          >

           ${
            esc(
             createdLabel(
              j
             )
            )
           }

          </div>

         </div>

         <div class="w-24 shrink-0 text-sm">

          ${j.total}

          ${
           t(
            'documents',
            'Dokumente'
           )
          }

         </div>

         <div class="flex-1">

          <div class="h-2 bg-gray-100 rounded-full overflow-hidden">

           ${
            jobActivity(j)?.kind==='run'
             ?`
              <div class="h-2 bg-amber-400 rounded-full processing-bar">
              </div>
             `
             :`
              <div
               class="h-2 bg-[#f5c400] rounded-full"
               style="width:${
                j.total
                 ?100*j.reviewed/j.total
                 :0
               }%"
              >
              </div>
             `
           }

          </div>

         </div>

         <div class="w-28 shrink-0 text-xs">

          ${j.reviewed}

          ${
           t(
            'reviewed',
            'geprüft'
           )
          }

         </div>

         <div class="flex items-center gap-2 shrink-0">

          <button
           ${
            disabled(
             busy()
            )
           }
           onclick="openJob('${j.id}')"
           class="px-3 py-1.5 border rounded-lg text-xs hover:bg-gray-50"
          >

           ${
            t(
             'Open',
             'Öffnen'
            )
           }

          </button>

          <button
           ${
            disabled(
             busy()
            )
           }
           onclick="deleteJob('${j.id}')"
           class="px-3 py-1.5 border border-red-200 text-red-600 rounded-lg text-xs hover:bg-red-50"
          >

           ${
            t(
             'Delete',
             'Löschen'
            )
           }

          </button>

         </div>

        </div>

       `
      )
      .join('')
      ||
      `
       <p class="p-5 text-sm text-gray-500">

        ${
         t(
          'No jobs yet. Upload a plan to begin.',
          'Noch keine Aufträge. Laden Sie einen Plan hoch.'
         )
        }

       </p>
      `
     }

    </div>

   </div>

  </main>

 </div>
 `;
}

function upload(){

 return `
 <div class="h-full flex flex-col">

  ${header()}

  <main class="p-8 max-w-6xl w-full mx-auto overflow-auto">

   <div class="mb-7">

    <h1 class="text-2xl font-bold">

     ${
      t(
       'New job',
       'Neuer Auftrag'
      )
     }

    </h1>

    <p class="text-sm text-gray-500 mt-1">

     ${
      t(
       'Upload plans, inspect the images, and review their three metadata fields.',
       'Pläne hochladen, Bilder prüfen und die drei Metadatenfelder bearbeiten.'
      )
     }

    </p>

   </div>

   <div class="flex gap-8">

    <div class="flex-1">

     <div class="bg-white border rounded-xl p-8">

      <div class="flex items-center gap-3 mb-6">

       <div class="w-8 h-8 rounded-full bg-[#f5c400] flex items-center justify-center font-bold">
        1
       </div>

       <div>

        <div class="font-semibold">

         ${
          t(
           'Add files',
           'Dateien hinzufügen'
          )
         }

        </div>

        <div class="text-xs text-gray-500">

         ${
          t(
           'Files, folders or ZIP archives · no file-count limit',
           'Dateien, Ordner oder ZIP-Archive · keine Anzahlbegrenzung'
          )
         }

        </div>

       </div>

      </div>

      <div
       ondragover="event.preventDefault()"
       ondrop="event.preventDefault();handleFiles(event.dataTransfer.files)"
       class="border-2 border-dashed border-gray-300 hover:border-[#d8b000] rounded-xl p-12 text-center bg-gray-50 cursor-pointer"
       onclick="document.getElementById('fileInput').click()"
      >

       <div class="text-3xl mb-3">
        ↑
       </div>

       <div class="font-semibold">

        ${
         t(
          'Drag files here',
          'Dateien hierher ziehen'
         )
        }

       </div>

       <div class="text-sm text-gray-500 mt-1">

        ${
         t(
          'or choose files',
          'oder Dateien auswählen'
         )
        }

       </div>

       <div class="text-xs text-gray-400 mt-4">
        TIFF · PNG · JPG · ZIP
       </div>

       <input
        id="fileInput"
        type="file"
        accept=".tif,.tiff,.png,.jpg,.jpeg,.zip"
        multiple
        class="hidden"
        onchange="handleFiles(this.files)"
       >

      </div>

      <div class="flex gap-3 mt-4">

       <button
        ${
         disabled(
          busy()
         )
        }
        onclick="document.getElementById('fileInput').click()"
        class="border rounded-lg px-3 py-2 text-sm"
       >

        ${
         t(
          'Choose files / ZIP',
          'Dateien / ZIP auswählen'
         )
        }

       </button>

       <button
        ${
         disabled(
          busy()
         )
        }
        onclick="document.getElementById('folderInput').click()"
        class="border rounded-lg px-3 py-2 text-sm"
       >

        ${
         t(
          'Choose folder',
          'Ordner auswählen'
         )
        }

       </button>

       <input
        id="folderInput"
        type="file"
        webkitdirectory
        directory
        multiple
        class="hidden"
        onchange="handleFiles(this.files)"
       >

      </div>

      <div class="text-xs text-gray-500 mt-3">

       ${ui.files.length}

       ${
        t(
         'selected',
         'ausgewählt'
        )
       }

       ·
       ${esc(uploadProgress)}

      </div>

      <div
       class="mt-5 space-y-2"
       style="max-height:280px;overflow:auto"
      >

       ${
        ui.files
        .map(
         (
          f,
          i
         )=>`

          <div class="border rounded-lg px-3 py-2 text-xs flex justify-between">

           <span>

            ${
             esc(
              f.webkitRelativePath
              ||f.name
             )
            }

            ·

            ${
             (
              f.size
              /1048576
             ).toFixed(1)
            }

            MB

           </span>

           <button
            ${
             disabled(
              busy()
             )
            }
            onclick="ui.files.splice(${i},1);render()"
           >
            ×
           </button>

          </div>

         `
        )
        .join('')
       }

      </div>

      <div class="mt-6 flex justify-between items-center">

       <span class="text-xs text-gray-500">

        ${
         t(
          'Originals and reviews are saved locally.',
          'Originale und Prüfungen werden lokal gespeichert.'
         )
        }

       </span>

       <button
        ${
         disabled(
          busy()
          ||!ui.files.length
         )
        }
        onclick="createJob()"
        class="bg-[#f5c400] font-semibold px-5 py-2.5 rounded-lg"
       >

        ${
         reading
          ?t(
            'Loading…',
            'Laden…'
           )
          :ui.mode==='backend'
           ?t(
             'Start processing',
             'Verarbeitung starten'
            )
           :t(
             'Open for review',
             'Zur Prüfung öffnen'
            )
        }

       </button>

      </div>

     </div>

    </div>

    <div class="w-80 space-y-4">

     <div class="bg-white border rounded-xl p-5">

      <div class="font-semibold text-sm">

       ${
        t(
         'Job',
         'Auftrag'
        )
       }

      </div>

      <div class="mt-4 text-xs text-gray-500">

       ${
        t(
         'Assigned job name',
         'Zugewiesener Auftragsname'
        )
       }

      </div>

      <div
       class="mt-1 text-2xl font-bold"
       aria-label="${
        t(
         'Assigned job name',
         'Zugewiesener Auftragsname'
        )
       }"
      >

       ${
        data.job?.processing_status
        ==='uploading'
         ?esc(
           jobLabel(
            data.job
           )
          )
         :'J'
          +esc(
           data.next_job_number
           ||'…'
          )
       }

      </div>

      <p class="text-xs text-gray-500 mt-2">

       ${
        t(
         'Assigned automatically when the upload starts.',
         'Wird beim Start des Uploads automatisch vergeben.'
        )
       }

      </p>

      <label class="block text-xs text-gray-500 mt-4 mb-1.5">

       ${
        t(
         'Mode',
         'Modus'
        )
       }

      </label>

      <select
       onchange="ui.mode=this.value;render()"
       class="w-full border rounded-lg px-3 py-2 text-sm"
      >

       <option
        value="manual"
        ${
         ui.mode==='manual'
          ?'selected'
          :''
        }
       >

        ${
         t(
          'Manual review',
          'Manuelle Prüfung'
         )
        }

       </option>

       <option
        value="backend"
        ${
         ui.mode==='backend'
          ?'selected'
          :''
        }
       >

        ${
         t(
          'Automatic review',
          'Automatische Prüfung'
         )
        }

       </option>

      </select>

      <p class="text-xs text-gray-500 mt-3">

       ${
        ui.mode==='manual'
         ?t(
           'Start with empty fields, then enter what you can read in the plan.',
           'Mit leeren Feldern beginnen und lesbare Angaben aus dem Plan eintragen.'
          )
         :t(
           'The backend returns the proposed station, line, and plan number.',
           'Das Backend liefert Bahnhof, Linie und Plannummer.'
          )
       }

      </p>

     </div>

    </div>

   </div>

  </main>

 </div>
 `;
}

function handleFiles(
 files
){

 if(
  busy()
 ){
  return;
 }

 const selected=[
  ...ui.files
 ];

 const names=
  new Set(
   selected.map(
    f=>
     f.webkitRelativePath
     ||f.name
   )
  );

 let skipped=
  0;

 for(
  const f
  of files
 ){

  const name=
   f.webkitRelativePath
   ||f.name;

  if(
   !/\.(tiff?|png|jpe?g|zip)$/i.test(
    name
   )
   ||names.has(
    name
   )
  ){

   skipped++;

   continue;
  }

  names.add(
   name
  );

  selected.push(
   f
  );
 }

 ui.files=
  selected;

 if(
  skipped
 ){

  showNotice(t(
   `${skipped} unsupported or duplicate selections skipped.`,
   `${skipped} nicht unterstützte oder doppelte Dateien übersprungen.`
  ));
 }

 render();
}

function readChunk(
 blob
){

 return new Promise(
  (
   resolve,
   reject
  )=>{

   const reader=
    new FileReader();

   reader.onload=
    ()=>resolve(
     reader.result
      .split(',')[1]
    );

   reader.onerror=
    ()=>reject(
     new Error(
      t(
       'Could not read a selected file.',
       'Eine Datei konnte nicht gelesen werden.'
      )
     )
    );

   reader.readAsDataURL(
    blob
   );
  }
 );
}

async function createJob(){

 if(
  busy()
  ||!ui.files.length
 ){
  return;
 }

 const chosen=[
  ...ui.files
 ];

 reading=
  true;

 render();

 try{

  await sendAsync(
   'begin_upload'
  );

  for(
   let i=0;
   i<chosen.length;
   i++
  ){

   const f=
    chosen[i];

   const name=
    f.webkitRelativePath
    ||f.name;

   const token=
    crypto.randomUUID();

   if(
    !f.size
   ){

    throw new Error(
     t(
      `Empty file: ${name}`,
      `Leere Datei: ${name}`
     )
    );
   }

   for(
    let offset=0;
    offset<f.size;
    offset+=4*1024*1024
   ){

    uploadProgress=
     `${i+1} / ${chosen.length} · ${name} · ${Math.round(100*offset/f.size)}%`;

    const encoded=
     await readChunk(
      f.slice(
       offset,
       offset+4*1024*1024
      )
     );

    await sendAsync(
     'upload_chunk',
     {
      token,
      name,
      size:f.size,
      offset,
      data:encoded
     }
    );
   }
  }

  uploadProgress=
   t(
    'Upload complete',
    'Upload abgeschlossen'
   );

  await sendAsync(
   'finish_upload',
   {
    mode:ui.mode
   },
   'review'
  );

  ui.files=[];

 }catch(error){

  const message=
   error.message;

  if(
   data.job?.processing_status
   ==='uploading'
  ){

   try{

    await sendAsync(
     'stop_upload'
    );

   }catch(_){}
  }

  showNotice(
   message
  );

  if(
   data.job?.documents.length
  ){

   ui.view=
    'review';
  }

 }finally{

  reading=
   false;

  render();
 }
}

function openExport(){

 if(
  busy()
 ){

  showNotice(t(
   'Please wait for the current action.',
   'Bitte warten Sie auf den aktuellen Vorgang.'
  ));

  render();

  return;
 }

 if(
  dirty(
   doc()
  )
 ){

  const d=
   doc();

  send(
   'save',
   {
    doc_id:d.id,

    values:{
     ...values(d)
    }
   }
  );

  pending.openExport=
   true;

 }else{

  ui.export=
   true;

  render();
 }
}

function exportModal(){

 const count=
  data.job?.documents.filter(
   d=>
    d.review_status==='reviewed'
  ).length
  ||0;

 return modal(
  `
   <h2 class="font-semibold text-lg">

    ${
     t(
      'Export reviewed results',
      'Geprüfte Ergebnisse exportieren'
     )
    }

   </h2>

   <p class="text-sm text-gray-500 mt-3">

    ${
     t(
      'Exports use your saved, corrected values.',
      'Exportiert werden Ihre gespeicherten, korrigierten Werte.'
     )
    }

   </p>

   <select
    onchange="ui.scope=this.value;render()"
    class="w-full border rounded-lg px-3 py-2 mt-4"
   >

    <option
     value="reviewed"
     ${
      ui.scope==='reviewed'
       ?'selected'
       :''
     }
    >

     ${
      t(
       'Reviewed documents only',
       'Nur geprüfte Dokumente'
      )
     }

     (${count})

    </option>

    <option
     value="all"
     ${
      ui.scope==='all'
       ?'selected'
       :''
     }
    >

     ${
      t(
       'All documents, with review status',
       'Alle Dokumente mit Prüfstatus'
      )
     }

     (${data.job?.documents.length||0})

    </option>

   </select>

   <div class="flex gap-3 mt-5">

    <button
     ${
      disabled(
       busy()
       ||!data.job
       ||(
        ui.scope==='reviewed'
        &&!count
       )
      )
     }
     onclick="send('export',{format:'csv',scope:ui.scope})"
     class="bg-bvg px-4 py-2 rounded-lg font-semibold"
    >
     CSV ↓
    </button>

    <button
     ${
      disabled(
       busy()
       ||!data.job
       ||(
        ui.scope==='reviewed'
        &&!count
       )
      )
     }
     onclick="send('export',{format:'json',scope:ui.scope})"
     class="border px-4 py-2 rounded-lg"
    >
     JSON ↓
    </button>

   </div>

   <p class="text-xs text-gray-500 mt-4">

    ${
     t(
      'CSV includes the three fields and review status. JSON also includes original values and manual-change flags.',
      'CSV enthält die drei Felder und den Prüfstatus. JSON enthält zusätzlich Originalwerte und Kennzeichnungen manueller Änderungen.'
     )
    }

   </p>
  `,
  'ui.export=false;render()'
 );
}

function modal(
 content,
 close
){

 return `
  <div
   class="fixed inset-0 flex items-center justify-center p-8"
   style="z-index:40;background:#0007"
  >

   <div
    class="bg-white border rounded-xl p-6 w-full relative"
    style="max-width:580px;max-height:90vh;overflow:auto"
   >

    <button
     onclick="${close}"
     class="absolute top-3 right-4 text-xl"
    >
     ×
    </button>

    ${content}

   </div>

  </div>
 `;
}

function help(){

 return modal(
  `
   <h2 class="font-semibold text-lg">

    ${
     t(
      'Review workflow',
      'Prüfablauf'
     )
    }

   </h2>

   <ol class="text-sm text-gray-600 mt-4 space-y-3">

    <li>

     1.
     ${
      t(
       'Create a job and upload plans.',
       'Auftrag erstellen und Pläne hochladen.'
      )
     }

    </li>

    <li>

     2.
     ${
      t(
       'The backend processes the uploaded plans.',
       'Das Backend verarbeitet die hochgeladenen Pläne.'
      )
     }

    </li>

    <li>

     3.
     ${
      t(
       'Review station, line and plan number.',
       'Bahnhof, Linie und Plannummer prüfen.'
      )
     }

    </li>

    <li>

     4.
     ${
      t(
       'Export reviewed documents as CSV or JSON.',
       'Geprüfte Dokumente als CSV oder JSON exportieren.'
      )
     }

    </li>

   </ol>

  `,
  'ui.help=false;render()'
 );
}

function render(
 preserveFocus=false
){

 const active=
  document.activeElement;

 const focus=
  active?.tagName==='INPUT'
   ?{
     id:active.id,

     label:
      active.getAttribute(
       'aria-label'
      ),

     start:
      active.selectionStart,

     end:
      active.selectionEnd
    }
   :null;

 document.documentElement.lang=
  ui.language;

 document.body.classList.toggle(
  'dark',
  ui.dark
 );

 document.getElementById(
  'app'
 ).innerHTML=`

  <div class="flex h-screen overflow-hidden">

   ${nav()}

   <div class="flex-1 min-w-0">

    ${
     ui.view==='upload'
      ?upload()
      :ui.view==='review'
       ?review()
       :dashboard()
    }

   </div>

  </div>

  ${
   ui.export
    ?exportModal()
    :''
  }

  ${
   ui.help
    ?help()
    :''
  }

  ${
   data.error
   ||notice
    ?`

     <div class="notice bg-white border rounded-lg px-4 py-3 text-sm shadow-lg flex gap-4">

      <span style="overflow-wrap:anywhere">

       ${
        esc(
         data.error
         ||notice
        )
       }

      </span>

      <button
       onclick="hideNotice()"
      >
       ×
      </button>

     </div>

    `
    :''
  }

 `;

 if(
  focus
  &&(
   focus.id
   ||focus.label
  )
 ){

  const el=
   focus.id
    ?document.getElementById(
      focus.id
     )
    :[
      ...document.querySelectorAll(
       'input'
      )
     ]
     .find(
      e=>
       e.getAttribute(
        'aria-label'
       )
       ===focus.label
     );

  if(
   el
  ){

   el.focus();

   el.setSelectionRange(
    focus.start,
    focus.end
   );
  }
 }

 requestAnimationFrame(
  drawPreview
 );

 armNotice();
}

document.addEventListener(
 'keydown',
 e=>{

  if(
   e.ctrlKey
   &&e.key==='Enter'
   &&ui.view==='review'
   &&!busy()
   &&doc()
  ){

   e.preventDefault();

   saveReview(
    'reviewed'
   );

   return;
  }

  if(
   [
    'INPUT',
    'SELECT',
    'TEXTAREA'
   ].includes(
    e.target.tagName
   )
  ){
   return;
  }

  if(
   ui.view==='review'
   &&!busy()
  ){

   if(
    e.key==='ArrowRight'
   ){

    moveDoc(
     1
    );
   }

   if(
    e.key==='ArrowLeft'
   ){

    moveDoc(
     -1
    );
   }
  }
 }
);

window.addEventListener(
 'beforeunload',
 e=>{

  if(
   Object.values(
    drafts
   ).length
  ){

   e.preventDefault();

   e.returnValue='';
  }
 }
);

/*
 Status alle 10 Sekunden beim Backend abfragen.
*/
setInterval(
 ()=>{

  if(
   data.job?.processing_status
   ==='processing'
   &&!busy()
  ){

   send(
    'poll'
   );
  }
 },
 10000
);

post(
 'streamlit:componentReady',
 {
  apiVersion:1
 }
);

post(
 'streamlit:setFrameHeight',
 {
  height:900
 }
);

render();
