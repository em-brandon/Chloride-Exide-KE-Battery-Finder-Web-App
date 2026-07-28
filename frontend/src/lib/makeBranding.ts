// Car-manufacturer brand logos for the OEM Fitment brand grid
// (frontend/src/pages/admin/AdminVehicleData.tsx). Mirrors brandBranding.ts's
// shape (logo map + fallback) but for vehicle makes instead of battery brands.
//
// Logo images (frontend/src/assets/makes/*.png) are the "thumb" (256px)
// variant from filippofilip95/car-logos-dataset (MIT-licensed dataset/code;
// the underlying logo images are trademarks of their respective
// manufacturers, originally sourced via Carlogos.org). Used here only on the
// authenticated admin panel, never the public-facing site. 71 of our 76
// oem_fitment makes matched a logo; the rest (INEOS, LDV, MITSUBISHI FUSO,
// NISSAN DIESEL/UD, PIAGGIO) fall back to a generated monogram badge —
// see AdminVehicleData.tsx's MakeBadge component, which consumes this file.

import logoAbarth from '@/assets/makes/abarth.png'
import logoAcura from '@/assets/makes/acura.png'
import logoAlfaRomeo from '@/assets/makes/alfa-romeo.png'
import logoAlpine from '@/assets/makes/alpine.png'
import logoAudi from '@/assets/makes/audi.png'
import logoBentley from '@/assets/makes/bentley.png'
import logoBmw from '@/assets/makes/bmw.png'
import logoBuick from '@/assets/makes/buick.png'
import logoByd from '@/assets/makes/byd.png'
import logoCadillac from '@/assets/makes/cadillac.png'
import logoChery from '@/assets/makes/chery.png'
import logoChevrolet from '@/assets/makes/chevrolet.png'
import logoChrysler from '@/assets/makes/chrysler.png'
import logoCitroen from '@/assets/makes/citroen.png'
import logoCupra from '@/assets/makes/cupra.png'
import logoDacia from '@/assets/makes/dacia.png'
import logoDaewoo from '@/assets/makes/daewoo.png'
import logoDaihatsu from '@/assets/makes/daihatsu.png'
import logoDodge from '@/assets/makes/dodge.png'
import logoDongfeng from '@/assets/makes/dongfeng.png'
import logoDs from '@/assets/makes/ds.png'
import logoEicher from '@/assets/makes/eicher.png'
import logoFiat from '@/assets/makes/fiat.png'
import logoFord from '@/assets/makes/ford.png'
import logoFoton from '@/assets/makes/foton.png'
import logoGeely from '@/assets/makes/geely.png'
import logoGmc from '@/assets/makes/gmc.png'
import logoGreatWall from '@/assets/makes/great-wall.png'
import logoHaval from '@/assets/makes/haval.png'
import logoHino from '@/assets/makes/hino.png'
import logoHonda from '@/assets/makes/honda.png'
import logoHummer from '@/assets/makes/hummer.png'
import logoHyundai from '@/assets/makes/hyundai.png'
import logoInfiniti from '@/assets/makes/infiniti.png'
import logoIsuzu from '@/assets/makes/isuzu.png'
import logoJaguar from '@/assets/makes/jaguar.png'
import logoJeep from '@/assets/makes/jeep.png'
import logoKia from '@/assets/makes/kia.png'
import logoKtm from '@/assets/makes/ktm.png'
import logoLandRover from '@/assets/makes/land-rover.png'
import logoLexus from '@/assets/makes/lexus.png'
import logoLincoln from '@/assets/makes/lincoln.png'
import logoMahindra from '@/assets/makes/mahindra.png'
import logoMan from '@/assets/makes/man.png'
import logoMazda from '@/assets/makes/mazda.png'
import logoMercedesBenz from '@/assets/makes/mercedes-benz.png'
import logoMg from '@/assets/makes/mg.png'
import logoMini from '@/assets/makes/mini.png'
import logoMitsubishi from '@/assets/makes/mitsubishi.png'
import logoNissan from '@/assets/makes/nissan.png'
import logoOpel from '@/assets/makes/opel.png'
import logoPerodua from '@/assets/makes/perodua.png'
import logoPeugeot from '@/assets/makes/peugeot.png'
import logoPorsche from '@/assets/makes/porsche.png'
import logoProton from '@/assets/makes/proton.png'
import logoRam from '@/assets/makes/ram.png'
import logoRenault from '@/assets/makes/renault.png'
import logoRollsRoyce from '@/assets/makes/rolls-royce.png'
import logoRover from '@/assets/makes/rover.png'
import logoScania from '@/assets/makes/scania.png'
import logoSeat from '@/assets/makes/seat.png'
import logoSkoda from '@/assets/makes/skoda.png'
import logoSsangyong from '@/assets/makes/ssangyong.png'
import logoSubaru from '@/assets/makes/subaru.png'
import logoSuzuki from '@/assets/makes/suzuki.png'
import logoTata from '@/assets/makes/tata.png'
import logoTesla from '@/assets/makes/tesla.png'
import logoToyota from '@/assets/makes/toyota.png'
import logoVauxhall from '@/assets/makes/vauxhall.png'
import logoVolkswagen from '@/assets/makes/volkswagen.png'
import logoVolvo from '@/assets/makes/volvo.png'

export const MAKE_LOGO: Partial<Record<string, string>> = {
  'ABARTH': logoAbarth,
  'ACURA': logoAcura,
  'ALFA ROMEO': logoAlfaRomeo,
  'ALPINE': logoAlpine,
  'AUDI': logoAudi,
  'BENTLEY': logoBentley,
  'BMW': logoBmw,
  'BUICK': logoBuick,
  'BYD': logoByd,
  'CADILLAC': logoCadillac,
  'CHERY': logoChery,
  'CHEVROLET': logoChevrolet,
  'CHRYSLER': logoChrysler,
  'CITROEN': logoCitroen,
  'CUPRA': logoCupra,
  'DACIA': logoDacia,
  'DAEWOO': logoDaewoo,
  'DAIHATSU': logoDaihatsu,
  'DODGE': logoDodge,
  'DONGFENG': logoDongfeng,
  'DS': logoDs,
  'EICHER': logoEicher,
  'FIAT': logoFiat,
  'FORD': logoFord,
  'FOTON': logoFoton,
  'GEELY': logoGeely,
  'GMC': logoGmc,
  'GREAT WALL': logoGreatWall,
  'HAVAL': logoHaval,
  'HINO': logoHino,
  'HONDA': logoHonda,
  'HUMMER': logoHummer,
  'HYUNDAI': logoHyundai,
  'INFINITI': logoInfiniti,
  'ISUZU': logoIsuzu,
  'JAGUAR': logoJaguar,
  'JEEP': logoJeep,
  'KIA': logoKia,
  'KTM': logoKtm,
  'LANDROVER': logoLandRover,
  'LEXUS': logoLexus,
  'LINCOLN': logoLincoln,
  'MAHINDRA': logoMahindra,
  'MAN': logoMan,
  'MAZDA': logoMazda,
  'MERCEDES-BENZ': logoMercedesBenz,
  'MG': logoMg,
  'MINI': logoMini,
  'MITSUBISHI': logoMitsubishi,
  'NISSAN': logoNissan,
  'OPEL': logoOpel,
  'PERODUA': logoPerodua,
  'PEUGEOT': logoPeugeot,
  'PORSCHE': logoPorsche,
  'PROTON': logoProton,
  'RAM': logoRam,
  'RENAULT': logoRenault,
  'ROLLS-ROYCE': logoRollsRoyce,
  'ROVER': logoRover,
  'SCANIA': logoScania,
  'SEAT': logoSeat,
  'SKODA': logoSkoda,
  'SSANGYONG': logoSsangyong,
  'SUBARU': logoSubaru,
  'SUZUKI': logoSuzuki,
  'TATA': logoTata,
  'TESLA': logoTesla,
  'TOYOTA': logoToyota,
  'VAUXHALL': logoVauxhall,
  'VOLKSWAGEN': logoVolkswagen,
  'VOLVO': logoVolvo,
}

// Hand-picking distinct colors for 76 makes (the way brandBranding.ts's
// BRAND_COLOR does for 8 battery brands) isn't practical — instead hash the
// make name to a hue and keep saturation/lightness fixed, so every make
// (real logo or monogram fallback) gets a stable, distinct-enough accent
// color across repeated renders.
export function makeColor(make: string): string {
  let hash = 0
  for (let i = 0; i < make.length; i++) {
    hash = (hash << 5) - hash + make.charCodeAt(i)
    hash |= 0
  }
  const hue = Math.abs(hash) % 360
  return `hsl(${hue}, 62%, 45%)`
}
