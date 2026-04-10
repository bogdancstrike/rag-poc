import { Bar } from '@ant-design/plots'
import { theme } from 'antd'
import type { Trend } from '@/types'

interface Props {
  trends: Trend[]
  height?: number
}

const DIR_COLOR: Record<string, string> = {
  rising:  '#52c41a',
  falling: '#f5222d',
  stable:  '#faad14',
}

/**
 * Horizontal bar chart showing trends: label vs change_pct, coloured by direction.
 */
export function TrendAreaChart({ trends, height = 260 }: Props) {
  const { token } = theme.useToken()

  const data = trends.map((t) => ({
    label:     t.label,
    change:    Math.abs(t.change_pct),
    direction: t.direction,
    period:    t.time_period,
    color:     DIR_COLOR[t.direction] ?? token.colorPrimary,
  }))

  const config = {
    data,
    xField:     'change',
    yField:     'label',
    colorField: 'direction',
    scale: {
      color: {
        range: Object.values(DIR_COLOR),
        domain: Object.keys(DIR_COLOR),
      },
    },
    label: {
      text:     (d: any) => `${d.direction === 'falling' ? '↓' : d.direction === 'rising' ? '↑' : '→'} ${d.change.toFixed(1)}%`,
      position: 'right' as const,
      style: { fill: token.colorTextSecondary, fontSize: 11 },
    },
    tooltip: {
      items: [
        { field: 'label', name: 'Topic' },
        { field: 'direction', name: 'Direction' },
        { field: 'period', name: 'Period' },
      ],
    },
    axis: {
      x: { title: { text: 'Change %', style: { fill: token.colorTextSecondary } } },
      y: { label: { style: { fill: token.colorTextSecondary, fontSize: 11 } } },
    },
    legend: { color: { position: 'top' as const } },
  }

  return <Bar {...config} height={height} />
}
