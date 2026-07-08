import sharp from 'sharp'
import { readdir, stat } from 'node:fs/promises'
import { join, basename, extname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ASSETS_DIR = fileURLToPath(new URL('../src/assets', import.meta.url))
const QUALITY = 80

const targets = [
  'exide-max-logo.png',
  'spark-logo.png',
  'powerlast-logo.png',
  'supreme-logo.jpg',
  'sebang-logo.jpg',
  'sb-flooded-logo.png',
  'exide-agm-logo.png',
  'chlorideexidebrandlogo.png',
  'rider.png',
  'exide-efb-logo.jpg',
]

for (const filename of targets) {
  const input = join(ASSETS_DIR, filename)
  const output = join(ASSETS_DIR, basename(filename, extname(filename)) + '.webp')

  const before = (await stat(input)).size
  await sharp(input).webp({ quality: QUALITY }).toFile(output)
  const after = (await stat(output)).size

  const saved = (((before - after) / before) * 100).toFixed(1)
  console.log(`${filename.padEnd(36)} ${kb(before).padStart(7)} → ${kb(after).padStart(7)}  (-${saved}%)`)
}

function kb(bytes) { return (bytes / 1024).toFixed(1) + ' kB' }
