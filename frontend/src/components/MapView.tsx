import { useEffect, useRef } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import './MapView.css'

const BASEMAP_STYLE_URL = 'https://tiles.openfreemap.org/styles/liberty'

export function MapView() {
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!containerRef.current) {
      return
    }

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASEMAP_STYLE_URL,
      center: [0, 20],
      zoom: 2,
    })

    return () => {
      map.remove()
    }
  }, [])

  return <div ref={containerRef} className="map-view" />
}
