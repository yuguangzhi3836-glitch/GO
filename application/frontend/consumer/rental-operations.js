/* Mount after rental-after-sales/deposit; the shared widget owns business actions. */
(() => {
  'use strict';
  for(const event of ['go:rental-operation-changed','go:rental-money-changed']){
    window.addEventListener(event,e=>{
      if(e.detail?.orderId===state.rentalOrder?.order_id){
        document.querySelector('[data-rental-deposit] [data-deposit-refresh]')?.click();
      }
    });
  }
  const previous=renderMobilityOrder;
  renderMobilityOrder=kind=>{
    previous(kind);if(kind!=='RENTAL'||!window.GORentalOperations)return;
    const orderId=state.rentalOrder.order_id;
    const container=document.createElement('section');container.className='card';container.dataset.rentalOperations='';
    document.querySelector('#app .shared-consumer-content').append(container);
    void window.GORentalOperations.render({container,orderId,request:(path,options)=>api(path,options?{...options,...(options.body!==undefined?{body:JSON.stringify(options.body)}:{})}:undefined)});
  };
})();
