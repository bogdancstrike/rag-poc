import { Bar } from '@ant-design/plots'
import { theme } from 'antd'
import type { Entity } from '@/types'

interface Props {
  entities: Entity[]
  height?: number
}

/** Horizontal bar: entity name vs frequency, coloured by type */
export function EntityBarChart({ entities, height = 260 }: Props) {
  const { token } = theme.useToken()

  const data = [...entities]
    .sort((a, b) => b.frequency - a.frequency)
    .slice(0, 15)  // top 15 entities

  const config = {
    data,
    xField:     'frequency',
    yField:     'name',
    colorField: 'type',
    label: {
      text: (d: Entity) => `${d.frequency}`,
      position: 'right' as const,
      style: { fill: token.colorTextSecondary, fontSize: 11 },
    },
    tooltip: {
      items: [
        { field: 'name', name: 'Entity' },
        { field: 'type', name: 'Type' },
        { field: 'frequency', name: 'Mentions' },
      ],
    },
    axis: {
      x: { title: { text: 'Mentions', style: { fill: token.colorTextSecondary } } },
      y: { label: { style: { fill: token.colorTextSecondary, fontSize: 11 } } },
    },
    legend: { color: { position: 'top' as const } },
  }

  return <Bar {...config} height={height} />
}
