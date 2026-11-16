import { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import type { Activity, PlaceResult } from './types';

interface Props {activities:Activity[];places:Record<string,PlaceResult>;numbers:Record<string,number>;selectedId:string|null;onSelect:(id:string)=>void}
export function TripMap({activities,places,numbers,selectedId,onSelect}:Props){
  const container=useRef<HTMLDivElement>(null);
  const mapRef=useRef<L.Map|null>(null);
  const layers=useRef<L.LayerGroup|null>(null);
  const markerRefs=useRef<Record<string,L.Marker>>({});
  const selectRef=useRef(onSelect);selectRef.current=onSelect;
  useEffect(()=>{
    if(!container.current)return;
    const map=L.map(container.current,{scrollWheelZoom:false,zoomAnimation:false,fadeAnimation:false,markerZoomAnimation:false}).setView([41.399,2.164],13);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',maxZoom:19}).addTo(map);
    mapRef.current=map;layers.current=L.layerGroup().addTo(map);
    const observer=new ResizeObserver(()=>map.invalidateSize({animate:false}));observer.observe(container.current);
    return()=>{observer.disconnect();map.remove();mapRef.current=null;layers.current=null;};
  },[]);
  useEffect(()=>{
    const map=mapRef.current,layer=layers.current;if(!map||!layer)return;
    layer.clearLayers();markerRefs.current={};const points:L.LatLngTuple[]=[];
    activities.forEach(activity=>{
      const place=places[activity.id]?.place;if(!place)return;
      const number=numbers[activity.id],point:L.LatLngTuple=[place.lat,place.lng];points.push(point);
      const icon=L.divIcon({className:'',html:`<div class="map-pin" data-stop="${number}">${number}</div>`,iconSize:[32,32],iconAnchor:[16,16]});
      const popup=document.createElement('div');const title=document.createElement('strong');title.textContent=`${number}. ${activity.name}`;
      const address=document.createElement('p');address.textContent=`${place.name} · ${place.address??'Address unavailable'}`;
      const link=document.createElement('button');link.type='button';link.className='map-popup-link';link.textContent='Find this stop in my itinerary';link.onclick=()=>selectRef.current(activity.id);
      popup.append(title,address,link);
      const tooltip=document.createElement('span');tooltip.textContent=`${number}. ${activity.name}`;
      const marker=L.marker(point,{icon,title:`${number}. ${activity.name}`,alt:`Stop ${number}: ${activity.name}`}).addTo(layer).bindPopup(popup).bindTooltip(tooltip,{direction:'top'});
      marker.on('click',()=>selectRef.current(activity.id));markerRefs.current[activity.id]=marker;
    });
    if(points.length)map.fitBounds(L.latLngBounds(points).pad(.25),{maxZoom:14,animate:false});
  },[activities,places,numbers]);
  useEffect(()=>{
    Object.entries(markerRefs.current).forEach(([id,marker])=>marker.getElement()?.querySelector('.map-pin')?.classList.toggle('selected',id===selectedId));
    const marker=selectedId?markerRefs.current[selectedId]:undefined;if(marker){marker.openPopup();mapRef.current?.panTo(marker.getLatLng(),{animate:false});}
  },[selectedId,activities,places]);
  return <div ref={container} className="map" role="region" aria-label="Itinerary map. Marker numbers match the numbered stops in your day plan."/>;
}
