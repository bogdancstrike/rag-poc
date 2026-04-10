import { Scatter } from '@ant-design/plots'
import { theme } from 'antd'
import type { HotTopic } from '@/types'

interface Props {
  topics: HotTopic[]
  height?: number
}

const SENTIMENT_COLOR: Record<string, string> = {
  positive: '#52c41a',
  negative: '#f5222d',
  neutral:  '#1890ff',
  mixed:    '#faad14',
}

/**
 * Bubble/scatter chart: x = topic index, y = count_estimate, size = prominence, colour = sentiment
 */
export function TopicBubbleChart({ topics, height = 280 }: Props) {
  const { token } = theme.useToken()

  const data = topics.map((t, i) => ({
    x:         i + 1,
    y:         t.count_estimate,
    size:      Math.sqrt(t.count_estimate) * 2,
    topic:     t.topic,
    sentiment: t.sentiment,
    color:     SENTIMENT_COLOR[t.sentiment] ?? token.colorPrimary,
  }))

  const config = {
    data,
    xField:    'x',
    yField:    'y',
    sizeField: 'size',
    colorField: 'sentiment',
    scale: {
      color: {
        range: Object.values(SENTIMENT_COLOR),
        domain: Object.keys(SENTIMENT_COLOR),
      },
      size: { range: [8, 36] },
    },
    point: { style: { fillOpacity: 0.75, lineWidth: 1 } },
    tooltip: {
      items: [
        { field: 'topic', name: 'Topic' },
        { field: 'y', name: 'Est. Count' },
        { field: 'sentiment', name: 'Sentiment' },
      ],
    },
    axis: {
      x: { label: false, title: false },
      y: {
        label: { style: { fill: token.colorTextSecondary } },
        title: { text: 'Est. Mentions', style: { fill: token.colorTextSecondary } },
      },
    },
    legend: {
      color: { position: 'bottom' as const, layout: { justifyContent: 'center' } },
    },
  }

  return <Scatter {...config} height={height} />
}
