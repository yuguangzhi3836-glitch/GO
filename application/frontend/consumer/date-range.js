(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.GODateRange=api;
})(typeof window!=='undefined'?window:null,function(){
  const DAY=/^\d{4}-\d{2}-\d{2}$/;
  const pad=n=>String(n).padStart(2,'0');
  const dayValue=d=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
  const monthValue=d=>`${d.getFullYear()}-${pad(d.getMonth()+1)}`;
  const dayOnly=v=>String(v||'').slice(0,10);
  const timeOnly=(v,fallback)=>String(v||'').includes('T')?String(v).slice(11,16):fallback;

  function createSelection({allowSameDay=false,start='',end=''}={}){
    const state={start:dayOnly(start)||null,end:dayOnly(end)||null,status:'EMPTY'};
    if(state.start&&state.end)state.status='COMPLETE';
    function select(value){
      if(!DAY.test(value))throw new Error('INVALID_DATE');
      if(!state.start||state.end){
        state.start=value;state.end=null;state.status='WAITING_END';return snapshot();
      }
      if(value<state.start){
        state.start=value;state.end=null;state.status='RESTARTED';return snapshot();
      }
      if(value===state.start&&!allowSameDay){
        state.end=null;state.status='SAME_DAY_BLOCKED';return snapshot();
      }
      state.end=value;state.status='COMPLETE';return snapshot();
    }
    function snapshot(){return {...state,complete:Boolean(state.start&&state.end)}}
    return {select,snapshot};
  }

  function bind({startId,endId,allowSameDay=false,kind='date',labels={}}){
    const start=document.getElementById(startId),end=document.getElementById(endId);
    if(!start||!end)return null;
    if(start.goRangeBinding?.end===end)return start.goRangeBinding;
    const min=dayOnly(start.min)||dayValue(new Date()),max=dayOnly(end.max||start.max);
    // Text + readonly prevents iOS from opening a second native date picker.
    for(const input of [start,end]){const value=input.value;input.type='text';input.value=value;input.placeholder=kind==='datetime'?'请选择日期与时间':'请选择日期'}
    const open=()=>openPicker({start,end,allowSameDay,kind,labels,min,max});
    for(const input of [start,end]){
      input.readOnly=true;
      input.setAttribute('aria-haspopup','dialog');
      input.setAttribute('inputmode','none');
      input.addEventListener('click',event=>{event.preventDefault();open()});
      input.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open()}});
    }
    return start.goRangeBinding={open,end};
  }

  function openPicker({start,end,allowSameDay=false,kind='date',labels={},min='',max=''}){
    document.querySelector('.go-date-range-backdrop')?.remove();
    const model=createSelection({allowSameDay,start:start.value,end:end.value});
    const initial=dayOnly(start.value);
    const cursor=initial?new Date(initial+'T12:00:00'):new Date();
    cursor.setDate(1);
    const wrap=document.createElement('div');
    wrap.className='go-date-range-backdrop';
    wrap.innerHTML=`<section class="go-date-range" role="dialog" aria-modal="true" aria-labelledby="goDateRangeTitle">
      <header><button type="button" data-close aria-label="关闭">×</button><div><h2 id="goDateRangeTitle">${labels.title||'选择日期'}</h2><p data-prompt>先选${labels.start||'开始日期'}，再选${labels.end||'结束日期'}</p></div></header>
      <div class="go-date-range-summary"><span data-start>${labels.start||'开始日期'}：未选择</span><span data-end>${labels.end||'结束日期'}：未选择</span></div>
      <div class="go-calendar-nav"><button type="button" data-prev aria-label="上个月">‹</button><b data-month></b><button type="button" data-next aria-label="下个月">›</button></div>
      <div class="go-calendar-week" aria-hidden="true"><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span></div>
      <div class="go-calendar-grid" role="grid"></div>
      ${kind==='datetime'?'<div class="go-date-range-times"><label>取车时间<input data-start-time type="time"></label><label>还车时间<input data-end-time type="time"></label></div>':''}
      <p class="go-date-range-error" data-error role="status"></p>
      <button type="button" class="btn primary" data-confirm disabled>确认日期</button>
    </section>`;
    document.body.appendChild(wrap);
    const trigger=document.activeElement;
    const close=()=>{wrap.remove();if(trigger?.isConnected)trigger.focus()};
    wrap.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();close()}if(e.key==='Tab'){const nodes=[...wrap.querySelectorAll('button:not(:disabled),input')];const i=nodes.indexOf(document.activeElement);if(e.shiftKey&&i<=0){e.preventDefault();nodes.at(-1)?.focus()}else if(!e.shiftKey&&i===nodes.length-1){e.preventDefault();nodes[0]?.focus()}}});
    const startTime=wrap.querySelector('[data-start-time]'),endTime=wrap.querySelector('[data-end-time]');
    if(startTime)startTime.value=timeOnly(start.value,'09:00');
    if(endTime)endTime.value=timeOnly(end.value,'18:00');

    function valid(){
      const s=model.snapshot();
      if(!s.complete||s.end<s.start||(!allowSameDay&&s.end===s.start))return false;
      if((min&&s.start<min)||(max&&s.end>max))return false;
      return kind!=='datetime'||s.start!==s.end||endTime.value>startTime.value;
    }
    function refresh(){
      const s=model.snapshot();
      wrap.querySelector('[data-start]').textContent=`${labels.start||'开始日期'}：${s.start||'未选择'}`;
      wrap.querySelector('[data-end]').textContent=`${labels.end||'结束日期'}：${s.end||'未选择'}`;
      const prompt=wrap.querySelector('[data-prompt]'),error=wrap.querySelector('[data-error]');
      prompt.textContent=s.complete?'日期区间已选好，请确认':s.start?`已选${labels.start||'开始日期'}，请选择${labels.end||'结束日期'}`:`请选择${labels.start||'开始日期'}，然后选择${labels.end||'结束日期'}`;
      error.textContent=s.status==='SAME_DAY_BLOCKED'?'该业务的结束日期必须晚于开始日期':s.status==='RESTARTED'?'已将较早日期设为新的开始日期，请继续选择结束日期':kind==='datetime'&&s.complete&&!valid()?'还车时间必须晚于取车时间':'';
      wrap.querySelector('[data-confirm]').disabled=!valid();
      render();
    }
    function render(){
      const year=cursor.getFullYear(),month=cursor.getMonth();
      wrap.querySelector('[data-month]').textContent=`${year}年${month+1}月`;
      const first=(new Date(year,month,1).getDay()+6)%7;
      const total=new Date(year,month+1,0).getDate();
      const state=model.snapshot(),cells=[];
      for(let i=0;i<first;i++)cells.push('<span></span>');
      for(let day=1;day<=total;day++){
        const value=`${year}-${pad(month+1)}-${pad(day)}`;
        const selected=value===state.start||value===state.end;
        const inRange=state.start&&state.end&&value>state.start&&value<state.end;
        const disabled=(min&&value<min)||(max&&value>max);
        cells.push(`<button type="button" role="gridcell" data-day="${value}" aria-label="${value}${value===state.start?' '+(labels.start||'开始'):value===state.end?' '+(labels.end||'结束'):''}" aria-pressed="${selected}" ${disabled?'disabled':''} class="${selected?'selected ':''}${inRange?'in-range':''}">${day}</button>`);
      }
      const grid=wrap.querySelector('.go-calendar-grid');
      grid.innerHTML=cells.join('');
      grid.querySelectorAll('[data-day]').forEach(button=>button.onclick=()=>{model.select(button.dataset.day);refresh()});
    }
    wrap.querySelector('[data-prev]').onclick=()=>{cursor.setMonth(cursor.getMonth()-1);render()};
    wrap.querySelector('[data-next]').onclick=()=>{cursor.setMonth(cursor.getMonth()+1);render()};
    wrap.querySelector('[data-close]').onclick=close;
    wrap.onclick=event=>{if(event.target===wrap)close()};
    if(startTime)startTime.oninput=refresh;
    if(endTime)endTime.oninput=refresh;
    wrap.querySelector('[data-confirm]').onclick=()=>{
      const s=model.snapshot();
      if(!valid())return;
      start.value=kind==='datetime'?`${s.start}T${startTime.value}`:s.start;
      end.value=kind==='datetime'?`${s.end}T${endTime.value}`:s.end;
      for(const input of [start,end])input.dispatchEvent(new Event('change',{bubbles:true}));
      close();
    };
    refresh();
    wrap.querySelector('[data-day]')?.focus();
    return {model,element:wrap};
  }

  return {createSelection,bind,openPicker,dayValue,monthValue};
});
