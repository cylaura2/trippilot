import type {Finding,PlaceResult} from './types';

/** Use confirmed coordinates so a similarly named business cannot change the destination. */
export function directionsURL(origin?:PlaceResult,destination?:PlaceResult,mode?:Finding['travel_mode']):string|null{
  if(origin?.status!=='resolved'||destination?.status!=='resolved'||!origin.place||!destination.place)return null;
  const from=origin.place,to=destination.place;
  if(![from.lat,from.lng,to.lat,to.lng].every(Number.isFinite))return null;
  const params=new URLSearchParams({api:'1',origin:`${from.lat},${from.lng}`,destination:`${to.lat},${to.lng}`});
  if(mode)params.set('travelmode',({walk:'walking',drive:'driving',approximated_transit:'transit'} as const)[mode]);
  return 'https://www.google.com/maps/dir/?'+params.toString();
}
