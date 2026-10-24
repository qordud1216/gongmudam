"use strict";
// URL에는 업무 문장을 넣지 않는다. 현재 탭의 임시 저장으로 한 번만 전달한다.
window.SeomuFlow=(()=>{
  const lifetime=30*60*1000;
  function write(kind,data){if(typeof data.text!=='string'||!data.text.trim()||data.text.length>3000)return false;try{sessionStorage.setItem('seomu-flow:'+kind,JSON.stringify({...data,created_at:Date.now()}));return true;}catch{return false;}}
  function take(kind){
    try{
      const key='seomu-flow:'+kind,raw=sessionStorage.getItem(key);if(!raw)return null;
      sessionStorage.removeItem(key);const data=JSON.parse(raw);
      if(typeof data.text!=='string'||!data.text.trim()||data.text.length>3000||!Number.isFinite(data.created_at)||Date.now()-data.created_at>lifetime||data.created_at>Date.now()+60000)return null;
      return {text:data.text,today:typeof data.today==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(data.today)?data.today:null,auto_submit:data.auto_submit===true,use_ai:data.use_ai===true};
    }catch{return null;}
  }
  return {write,take};
})();
