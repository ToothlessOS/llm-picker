const BAR = ['var(--home-art-teal)', 'var(--home-art-orange)', 'var(--home-art-slate)'] as const

const COST_ROWS = [
  [62, 22, 10],
  [48, 16, 8],
  [70, 24, 8],
  [28, 14, 8],
] as const

const HEATMAP = [
  ['var(--home-art-heat-1)', 'var(--home-art-heat-4)', 'var(--home-art-heat-3)', 'var(--home-art-heat-2)'],
  ['var(--home-art-heat-2)', 'var(--home-art-heat-1)', 'var(--home-art-heat-1)', 'var(--home-art-heat-3)'],
  ['var(--home-art-heat-4)', 'var(--home-art-heat-1)', 'var(--home-art-heat-2)', 'var(--home-art-heat-4)'],
  ['var(--home-art-heat-3)', 'var(--home-art-heat-1)', 'var(--home-art-heat-4)', 'var(--home-art-heat-2)'],
] as const

const COMMUNITY_BARS = [
  [78, 46, 62, 34],
  [52, 86, 48, 74],
] as const

export function CostBreakdownArt() {
  return (
    <svg className="home-art" viewBox="0 0 280 132" role="img" aria-label="Stacked cost bars">
      {COST_ROWS.map((parts, row) => {
        let x = 28
        const y = 8 + row * 32
        return (
          <g key={row}>
            <text x="4" y={y + 14} fill="var(--home-art-label)" fontSize="11" fontFamily="DM Sans, sans-serif">
              {String.fromCharCode(65 + row)}
            </text>
            {parts.map((width, index) => {
              const mark = (
                <rect key={index} x={x} y={y} width={width * 2.15} height="16" rx="2" fill={BAR[index]} />
              )
              x += width * 2.15 + 3
              return mark
            })}
          </g>
        )
      })}
    </svg>
  )
}

export function TaskFitArt() {
  return (
    <svg className="home-art" viewBox="0 0 280 148" role="img" aria-label="Task fit heatmap">
      {HEATMAP.map((row, y) =>
        row.map((fill, x) => (
          <rect
            key={`${x}-${y}`}
            x={28 + x * 58}
            y={8 + y * 26}
            width="50"
            height="18"
            rx="3"
            fill={fill}
          />
        )),
      )}
      {['Agent', 'Docs', 'Search', 'WebDev'].map((label, index) => (
        <text
          key={label}
          x={53 + index * 58}
          y="140"
          fill="var(--home-art-label)"
          fontSize="11"
          textAnchor="middle"
          fontFamily="DM Sans, sans-serif"
        >
          {label}
        </text>
      ))}
    </svg>
  )
}

export function ModelCardArt() {
  const cx = 140
  const cy = 72
  const radius = 48
  const point = (index: number, scale = 1) => {
    const angle = -Math.PI / 2 + (index * 2 * Math.PI) / 5
    return [cx + Math.cos(angle) * radius * scale, cy + Math.sin(angle) * radius * scale]
  }
  const ring = (scale: number) => point(0, scale).concat(point(1, scale), point(2, scale), point(3, scale), point(4, scale)).join(' ')
  const shape = [1, 0.72, 0.84, 0.55, 0.9]
    .map((scale, index) => point(index, scale).join(','))
    .join(' ')
  const labels = [
    ['Intel', point(0, 1.28)],
    ['Code', point(1, 1.32)],
    ['Agent', point(2, 1.28)],
    ['Cost', point(3, 1.28)],
    ['Speed', point(4, 1.34)],
  ] as const

  return (
    <svg className="home-art" viewBox="0 0 280 156" role="img" aria-label="Model profile radar">
      <polygon points={ring(0.45)} fill="none" stroke="var(--home-art-grid)" strokeWidth="1" />
      <polygon points={ring(1)} fill="none" stroke="var(--home-art-grid)" strokeWidth="1" />
      {[0, 1, 2, 3, 4].map((index) => {
        const [x, y] = point(index)
        return <line key={index} x1={cx} y1={cy} x2={x} y2={y} stroke="var(--home-art-grid)" strokeWidth="1" />
      })}
      <polygon points={shape} fill="var(--home-art-shape)" stroke="var(--home-art-stroke)" strokeWidth="1.6" />
      {labels.map(([label, [x, y]]) => (
        <text
          key={label}
          x={x}
          y={y}
          fill="var(--home-art-label)"
          fontSize="11"
          textAnchor="middle"
          dominantBaseline="middle"
          fontFamily="DM Sans, sans-serif"
        >
          {label}
        </text>
      ))}
    </svg>
  )
}

const FRONTIER = [
  [42, 218],
  [100, 174],
  [168, 130],
  [252, 92],
  [356, 60],
] as const

const BELOW = [
  [76, 212],
  [132, 196],
  [196, 220],
  [244, 174],
  [306, 142],
  [372, 158],
] as const

const PARALLEL_X = [446, 518, 590, 662] as const

const PARALLEL_RECORDS = [
  [208, 140, 174, 126],
  [190, 104, 154, 166],
  [168, 178, 132, 196],
  [146, 122, 92, 142],
  [118, 82, 116, 76],
  [96, 154, 70, 108],
  [72, 58, 86, 54],
  [52, 92, 48, 88],
] as const

const PARALLEL_HIGHLIGHTS = [
  [190, 104, 154, 166],
  [72, 58, 86, 54],
] as const

export function ExplorerArt() {
  const front = FRONTIER.map(([x, y], index) => `${index === 0 ? 'M' : 'L'}${x},${y}`).join(' ')
  const parallelPoints = (values: readonly number[]) =>
    values.map((y, index) => `${PARALLEL_X[index]},${y}`).join(' ')
  return (
    <svg
      className="home-art home-art--explorer"
      viewBox="0 0 700 270"
      role="img"
      aria-label="Cost against capability scatterplot with Pareto frontier and parallel coordinates"
    >
      <text x="28" y="18" fill="var(--home-art-label)" fontSize="11" fontFamily="DM Sans, sans-serif">
        Performance vs. cost
      </text>
      {[72, 132, 192].map((y) => (
        <line key={y} x1="28" x2="394" y1={y} y2={y} stroke="var(--home-art-grid)" />
      ))}
      <line x1="28" x2="28" y1="34" y2="232" stroke="var(--home-art-grid)" />
      <line x1="28" x2="394" y1="232" y2="232" stroke="var(--home-art-grid)" />
      <path d={front} fill="none" stroke="var(--home-art-teal)" strokeWidth="2" strokeDasharray="7 6" strokeLinecap="round" strokeLinejoin="round" />
      {BELOW.map(([x, y], index) => (
        <circle key={index} cx={x} cy={y} r="5.5" fill="var(--home-art-muted)" />
      ))}
      {FRONTIER.map(([x, y], index) => (
        <circle key={index} cx={x} cy={y} r="6.5" fill="var(--home-art-teal)" />
      ))}
      <text x="211" y="258" fill="var(--home-art-label)" fontSize="11" textAnchor="middle" fontFamily="DM Sans, sans-serif">
        Cost
      </text>

      <line x1="414" x2="414" y1="24" y2="244" stroke="var(--home-art-grid)" />
      <text x="440" y="18" fill="var(--home-art-label)" fontSize="11" fontFamily="DM Sans, sans-serif">
        Parallel coordinates
      </text>
      {PARALLEL_X.map((x, index) => (
        <g key={x}>
          <line x1={x} x2={x} y1="34" y2="232" stroke="var(--home-art-grid)" />
          <text
            x={x}
            y="258"
            fill="var(--home-art-label)"
            fontSize="10"
            textAnchor="middle"
            fontFamily="DM Sans, sans-serif"
          >
            {['Cost', 'Intel', 'Coding', 'Agent'][index]}
          </text>
        </g>
      ))}
      {PARALLEL_RECORDS.map((values, index) => (
        <polyline
          key={index}
          points={parallelPoints(values)}
          fill="none"
          stroke="var(--home-art-muted)"
          strokeWidth="1.25"
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity="0.42"
        />
      ))}
      {PARALLEL_HIGHLIGHTS.map((values, index) => (
        <polyline
          key={index}
          points={parallelPoints(values)}
          fill="none"
          stroke="var(--home-art-teal)"
          strokeWidth="2.25"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ))}
    </svg>
  )
}

export function CommunityArt() {
  return (
    <svg className="home-art home-art--community" viewBox="0 0 360 132" role="img" aria-label="Discussion bars">
      {COMMUNITY_BARS.map((column, columnIndex) =>
        column.map((width, row) => (
          <rect
            key={`${columnIndex}-${row}`}
            x={16 + columnIndex * 176}
            y={12 + row * 30}
            width={width * 1.7}
            height="14"
            rx="2"
            fill={row === 1 || (columnIndex === 1 && row === 2) ? 'var(--home-art-orange)' : row % 2 === 0 ? 'var(--home-art-teal)' : 'var(--home-art-teal-soft)'}
          />
        )),
      )}
    </svg>
  )
}
