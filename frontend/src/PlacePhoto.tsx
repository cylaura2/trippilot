import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Image as ImageIcon, Info, X, ArrowUpRight } from 'lucide-react';
import type { Place } from './types';

type Photo = {url:string;full_url?:string;source_url:string;author:string;license:string;license_url:string;title:string;provider?:string;attribution_required?:boolean};
type Result = {status:string;photo:Photo|null};
const requests = new Map<string,Promise<Result>>();
export function PlacePhoto({name,city,place}:{name:string;city:string;place?:Place|null}) {
  const [result,setResult] = useState<Result|null>(null);
  const [failed,setFailed] = useState(false);
  const [opened,setOpened] = useState(false);
  const key = name.trim() && name!=='New activity' ? JSON.stringify({name,matched_name:place?.name??name,city,lat:place?.lat??null,lng:place?.lng??null}) : '';
  useEffect(()=>{
    let active = true;
    setResult(null);setFailed(false);setOpened(false);
    if(key){
      if(!requests.has(key)){
        if(requests.size>=128)requests.delete(requests.keys().next().value!);
        requests.set(key,fetch('/api/places/photo',{method:'POST',headers:{'Content-Type':'application/json'},body:key})
          .then(response=>response.ok?response.json():{status:'unavailable',photo:null})
          .catch(()=>({status:'unavailable',photo:null})));
      }
      requests.get(key)!.then(value=>{if(active)setResult(value);});
    }
    return ()=>{active=false;};
  },[key]);
  const photo = !failed&&result?.photo;
  return <figure className="place-photo">
    {photo?<><button type="button" className="photo-open" aria-label={`Open photo of ${name}`} onClick={()=>setOpened(true)}><img src={photo.url} alt={photo.title} loading="lazy" onError={()=>setFailed(true)}/></button>{opened&&<PhotoViewer photo={photo} name={name} onClose={()=>setOpened(false)}/>}{photo.attribution_required!==false&&<details><summary aria-label={`Photo credits for ${name}`}><Info size={13}/><span className="sr-only">Photo attribution</span></summary><div><a href={photo.source_url} target="_blank" rel="noreferrer">{photo.title}</a><span>{photo.author}</span><a href={photo.license_url} target="_blank" rel="noreferrer">{photo.license}</a><small>Via {photo.provider??'Wikimedia Commons'} · cropped</small></div></details>}</>:<div className="photo-placeholder" title={result?.status==='missing'?'No matching photo was found in Wikimedia or Openverse. This does not affect your confirmed location.':undefined}><ImageIcon size={20}/><small>{!key?'Enter a place for a photo':!result?'Finding photo…':failed||result.status==='unavailable'?'Photo unavailable':'No matching photo'}</small></div>}
  </figure>;
}


function PhotoViewer({photo,name,onClose}:{photo:Photo;name:string;onClose:()=>void}){
  const dialog=useRef<HTMLDialogElement>(null);
  const [largeFailed,setLargeFailed]=useState(false);
  useEffect(()=>{
    const element=dialog.current;
    element?.showModal();
    return ()=>element?.close();
  },[]);
  return createPortal(<dialog ref={dialog} className="photo-viewer" aria-label={`Photo of ${name}`} onCancel={event=>{event.preventDefault();onClose();}} onClick={event=>{if(event.target===event.currentTarget)onClose();}}>
    <div className="photo-viewer-header"><h2>{name}</h2><button type="button" className="icon-button" aria-label="Close photo" onClick={onClose}><X size={23}/></button></div>
    <img className="photo-viewer-image" src={largeFailed?photo.url:photo.full_url??photo.url} alt={photo.title} onError={()=>setLargeFailed(true)}/>
    <div className="photo-viewer-caption"><p>{photo.title}</p>{photo.attribution_required!==false&&<small>{photo.author} · <a href={photo.license_url} target="_blank" rel="noopener noreferrer">{photo.license}</a> · {photo.provider??'Wikimedia Commons'}</small>}<a className="directions-link" href={photo.source_url} target="_blank" rel="noopener noreferrer">View original source<ArrowUpRight size={14}/></a></div>
  </dialog>,document.body);
}
