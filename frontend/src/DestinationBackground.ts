import {useEffect,useState} from 'react';
export interface BackgroundPhoto {url:string;source_url:string;title:string;author:string;license:string;license_url:string;attribution_required:boolean}
export function useDestinationPhoto(city:string|null){
  const [photo,setPhoto]=useState<{city:string;photo:BackgroundPhoto}|null>(null);
  useEffect(()=>{
    setPhoto(null);
    if(!city)return;
    let active=true;
    const controller=new AbortController();
    fetch('/api/destination/photo',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({city}),signal:controller.signal})
      .then(response=>response.ok?response.json():null).then(result=>{
        if(!active||!result?.photo)return;
        const image=new Image();
        image.onload=()=>{if(active)setPhoto({city,photo:result.photo});};
        image.src=result.photo.url;
      }).catch(()=>{});
    return ()=>{active=false;controller.abort();};
  },[city]);
  return photo?.city===city?photo.photo:null;
}
