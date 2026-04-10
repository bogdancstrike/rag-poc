import { useEffect, useRef, useState, useMemo } from 'react'
import cloud from 'd3-cloud'
import * as d3 from 'd3'

interface WordItem {
  label: string
  value: number
}

interface Props {
  words: WordItem[]
  maxWords?: number
  height?: number
}

const PALETTE = [
  '#1890ff', '#52c41a', '#fa8c16', '#722ed1', '#eb2f96',
  '#13c2c2', '#f5222d', '#2f54eb', '#faad14', '#389e0d',
  '#08979c', '#c41d7f', '#d4380d', '#7cb305', '#096dd9',
]

/**
 * WordCloud — renders a d3-cloud word cloud that waits for the container to
 * have a real width (via ResizeObserver) before computing the layout.
 * This prevents the "all words at 0,0" bug that happens when layout runs
 * before the DOM is painted.
 */
export function WordCloud({ words, maxWords = 60, height = 300 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const [width, setWidth] = useState(0)

  // Measure real container width after paint, keep updating on resize
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => {
      const w = entry.contentRect.width
      if (w > 0) setWidth(w)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const sorted = useMemo(() => {
    if (!words?.length) return []
    return [...words].sort((a, b) => b.value - a.value).slice(0, maxWords)
  }, [words, maxWords])

  useEffect(() => {
    if (!svgRef.current || !sorted.length || width === 0) return

    const max = sorted[0]?.value || 1
    const fontSize = d3.scaleSqrt().domain([0, max]).range([12, 58])

    let active = true
    const layoutInst = cloud<{ text: string; value: number; color: string }>()
      .size([width, height])
      .words(
        sorted.map((d, i) => ({
          text:  d.label,
          value: d.value,
          color: PALETTE[i % PALETTE.length],
        })),
      )
      .padding(5)
      .rotate(() => (Math.random() > 0.65 ? (Math.random() > 0.5 ? 90 : -90) : 0))
      .font('Inter, -apple-system, sans-serif')
      .fontSize((d) => fontSize(d.value!))
      .spiral('archimedean')
      .on('end', (placed) => {
        if (!active || !svgRef.current) return
        const svg = d3.select(svgRef.current)
        svg.selectAll('*').remove()
        svg.attr('width', width).attr('height', height)

        const g = svg.append('g')
          .attr('transform', `translate(${width / 2},${height / 2})`)

        g.selectAll('text')
          .data(placed)
          .join('text')
          .style('font-size', (d) => `${d.size}px`)
          .style('font-family', 'Inter, -apple-system, sans-serif')
          .style('font-weight', (d) => (d.size! > 32 ? 700 : d.size! > 20 ? 600 : 400))
          .style('fill', (d: any) => d.color)
          .style('cursor', 'default')
          .style('user-select', 'none')
          .attr('text-anchor', 'middle')
          .attr('transform', (d) => `translate(${d.x},${d.y}) rotate(${d.rotate})`)
          .text((d) => d.text!)
          .append('title')
          .text((d: any) => `${d.text}: ${d.value}`)
      })

    layoutInst.start()
    return () => {
      active = false
      layoutInst.stop()
    }
  }, [sorted, width, height])

  if (!sorted.length) return null

  return (
    <div ref={containerRef} style={{ width: '100%', overflow: 'hidden', borderRadius: 8 }}>
      <svg ref={svgRef} style={{ display: 'block', width: '100%', height }} />
    </div>
  )
}
