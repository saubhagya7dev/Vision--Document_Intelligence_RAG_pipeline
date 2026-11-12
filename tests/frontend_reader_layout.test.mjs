import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
function load(saved) {
    const handlers={}, attrs={}, storage=new Map(saved === undefined ? [] : [['vr_reader_width',String(saved)]]), styles={}, body=new Set();
    const handle={addEventListener:(name,fn)=>handlers[name]=fn,setAttribute:(k,v)=>attrs[k]=String(v),getAttribute:k=>attrs[k],focus(){},setPointerCapture(){}};
    const workbench={clientWidth:1000,style:{setProperty:(k,v)=>styles[k]=v}};
    const panel={getBoundingClientRect:()=>({width:Number.parseInt(styles['--reader-width'])})};
    let resize;
    const window={addEventListener(){}};
    vm.runInNewContext(fs.readFileSync('src/vision_rag/static/reader-layout.js','utf8'),{window,localStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},document:{body:{classList:{add:k=>body.add(k),remove:k=>body.delete(k)}}},ResizeObserver:class{constructor(fn){resize=fn;}observe(){}}});
    window.VisionReaderLayout.setup(workbench,panel,handle);
    return {api:window.VisionReaderLayout,handlers,attrs,styles,storage,workbench,resize:()=>resize(),body};
}
test('reader width is bounded so the conversation retains useful space',()=>{
    const d=load(); assert.equal(d.styles['--reader-width'],'340px');
    assert.equal(d.api.clamp(900,1000),660); assert.equal(d.api.clamp(20,1000),260);
    assert.equal(d.api.clamp(NaN,1000),340); assert.equal(d.api.clamp(900,2000),720);
});
test('keyboard resizing persists preference and responds to container size',()=>{
    const d=load(420); let prevented=false;
    d.handlers.keydown({key:'ArrowLeft',shiftKey:true,preventDefault(){prevented=true;}});
    assert.equal(prevented,true); assert.equal(d.storage.get('vr_reader_width'),'470');
    assert.equal(d.attrs['aria-valuenow'],'470');
    d.workbench.clientWidth=700; d.resize(); assert.equal(d.attrs['aria-valuenow'],'360');
    d.workbench.clientWidth=1000; d.resize(); assert.equal(d.attrs['aria-valuenow'],'470');
    d.handlers.dblclick(); assert.equal(d.attrs['aria-valuenow'],'340'); assert.equal(d.storage.has('vr_reader_width'),false);
});
test('pointer resizing is clamped and cancellation always clears dragging state',()=>{
    const d=load(); d.handlers.pointerdown({button:0,clientX:650,pointerId:1,preventDefault(){}});
    d.handlers.pointermove({clientX:450}); assert.equal(d.attrs['aria-valuenow'],'540');
    d.handlers.pointermove({clientX:0}); assert.equal(d.attrs['aria-valuenow'],'660');
    assert.equal(d.body.has('reader-resizing'),true);
    d.handlers.pointercancel(); assert.equal(d.body.has('reader-resizing'),false); assert.equal(d.storage.get('vr_reader_width'),'660');
    d.handlers.pointermove({clientX:700}); assert.equal(d.attrs['aria-valuenow'],'660');
});
