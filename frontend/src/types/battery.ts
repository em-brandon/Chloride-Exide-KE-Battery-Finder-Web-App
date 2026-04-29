export interface BatteryEntry {
  battery_code: string
  model_key: string
  ah: number
  cca_en: number | null
  technology: string
}

export interface RecommendationResult {
  make: string
  model: string
  year: number
  engine_cc: number
  fuel_type: string
  battery_region: 'NS' | 'DIN'
  recommended_ah: number
  preferred_tech: string
  confidence: number
  match_type: string
  matched_make: string | null
  matched_model: string | null
  matched_year: number | null
  primary: BatteryEntry
  alternatives: BatteryEntry[]
}

export interface RecommendRequest {
  make: string
  model: string
  year: number
  engine_cc: number | null
  fuel_type: string | null
}
