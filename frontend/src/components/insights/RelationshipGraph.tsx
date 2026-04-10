import { useEffect, useRef, useMemo } from 'react'
import * as d3 from 'd3'
import { Typography } from 'antd'

const { Text } = Typography

interface GraphNode {
  id: string
  label: string
  type: string
}

interface GraphEdge {
  source: string
  target: string
  relationship: string
  weight?: number
}

interface Props {
  nodes: GraphNode[]
  edges: GraphEdge[]
  width?: number
  height?: number
}

/** Node type → fill colour */
const TYPE_COLORS: Record<string, string> = {
  person:   '#ff7875',
  org:      '#69b1ff',
  location: '#95de64',
  tool:     '#ffd666',
  event:    '#b37feb',
  default:  '#8c8c8c',
}

export function RelationshipGraph({ nodes, edges, width = 600, height = 380 }: Props) {
  const svgRef = useRef<SVGSVGElement>(null)

  /** Build maps for D3 simulation */
  const { simNodes, simLinks } = useMemo(() => {
    const simNodes = nodes.map((n) => ({ ...n }))
    const nodeById = new Map(simNodes.map((n) => [n.id, n]))
    const simLinks = edges
      .filter((e) => nodeById.has(e.source) && nodeById.has(e.target))
      .map((e) => ({
        source: e.source,
        target: e.target,
        relationship: e.relationship,
        weight: e.weight ?? 0.5,
      }))
    return { simNodes, simLinks }
  }, [nodes, edges])

  useEffect(() => {
    if (!svgRef.current || simNodes.length === 0) return
    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const g = svg.append('g')

    // Arrow marker definition
    svg.append('defs').append('marker')
      .attr('id', 'arrow')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 22)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', '#bfbfbf')

    // Force simulation
    const simulation = d3.forceSimulation<any>(simNodes as any)
      .force('link', d3.forceLink(simLinks as any).id((d: any) => d.id).distance(120))
      .force('charge', d3.forceManyBody().strength(-300))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide(30))

    // Links
    const link = g.append('g')
      .selectAll('line')
      .data(simLinks)
      .join('line')
      .attr('stroke', '#d9d9d9')
      .attr('stroke-width', (d: any) => Math.max(1, (d.weight || 0.5) * 3))
      .attr('marker-end', 'url(#arrow)')

    // Link labels
    const linkLabel = g.append('g')
      .selectAll('text')
      .data(simLinks)
      .join('text')
      .attr('font-size', 9)
      .attr('fill', '#8c8c8c')
      .attr('text-anchor', 'middle')
      .text((d: any) => d.relationship)

    // Nodes
    const node = g.append('g')
      .selectAll('g')
      .data(simNodes)
      .join('g')
      .call(
        d3.drag<any, any>()
          .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart()
            d.fx = d.x
            d.fy = d.y
          })
          .on('drag', (event, d) => {
            d.fx = event.x
            d.fy = event.y
          })
          .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0)
            d.fx = null
            d.fy = null
          }),
      )

    node.append('circle')
      .attr('r', 18)
      .attr('fill', (d: any) => TYPE_COLORS[d.type] || TYPE_COLORS.default)
      .attr('stroke', '#fff')
      .attr('stroke-width', 2)

    node.append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', 32)
      .attr('font-size', 10)
      .attr('fill', '#434343')
      .text((d: any) => { const l = d.label ?? d.id ?? ''; return l.length > 14 ? l.slice(0, 12) + '…' : l })

    node.append('title').text((d: any) => `${d.label ?? d.id ?? ''} (${d.type ?? ''})`)

    // Tick update
    simulation.on('tick', () => {
      link
        .attr('x1', (d: any) => d.source.x)
        .attr('y1', (d: any) => d.source.y)
        .attr('x2', (d: any) => d.target.x)
        .attr('y2', (d: any) => d.target.y)

      linkLabel
        .attr('x', (d: any) => (d.source.x + d.target.x) / 2)
        .attr('y', (d: any) => (d.source.y + d.target.y) / 2)

      node.attr('transform', (d: any) => `translate(${d.x},${d.y})`)
    })

    // Zoom + pan
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 4])
      .on('zoom', (event) => g.attr('transform', event.transform.toString()))

    svg.call(zoom as any)

    return () => {
      simulation.stop()
    }
  }, [simNodes, simLinks, width, height])

  if (simNodes.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: 20 }}>
        <Text type="secondary">No entities detected</Text>
      </div>
    )
  }

  return (
    <div style={{ position: 'relative' }}>
      <svg
        ref={svgRef}
        width={width}
        height={height}
        style={{ width: '100%', height, cursor: 'grab', background: '#fafafa', borderRadius: 8 }}
      />
      {/* Legend */}
      <div style={{ position: 'absolute', bottom: 8, right: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {Object.entries(TYPE_COLORS).filter(([k]) => k !== 'default').map(([type, color]) => (
          <span key={type} style={{ fontSize: 10, display: 'flex', alignItems: 'center', gap: 3 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, display: 'inline-block' }} />
            {type}
          </span>
        ))}
      </div>
      <div style={{ fontSize: 10, color: '#8c8c8c', marginTop: 4 }}>
        Drag nodes to reposition · Scroll to zoom · {simNodes.length} entities, {simLinks.length} relationships
      </div>
    </div>
  )
}
