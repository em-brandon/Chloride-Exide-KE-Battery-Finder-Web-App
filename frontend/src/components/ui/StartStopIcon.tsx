interface StartStopIconProps {
  size?: number
  color?: string
}

export function StartStopIcon({ size = 28, color = '#27DE2E' }: StartStopIconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 100 100"
      width={size}
      height={size}
      aria-hidden="true"
      style={{ flexShrink: 0 }}
    >
      {/* Clockwise arc — butt cap so the filled arrowhead covers the flat end */}
      <path
        d="M 31 83 A 38 38 0 1 1 69 83"
        fill="none"
        stroke={color}
        strokeWidth="7"
        strokeLinecap="butt"
      />
      {/*
        Arrowhead — base straddles the arc endpoint (69, 83); tip extends
        further along the CW direction (left-down, −0.866, +0.5).
        3:1 aspect ratio gives a sharp ~37° tip that reads clearly at small sizes.
      */}
      <polygon points="48,95 65,76 73,90" fill={color} />
      {/* Bold letter A */}
      <path
        d="M 35 71 L 50 27 L 65 71"
        fill="none"
        stroke={color}
        strokeWidth="7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <line
        x1="42" y1="54"
        x2="58" y2="54"
        stroke={color}
        strokeWidth="7"
        strokeLinecap="round"
      />
    </svg>
  )
}
