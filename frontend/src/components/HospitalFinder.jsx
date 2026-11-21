import React, { useEffect, useState } from 'react'
import {
  Building2,
  ExternalLink,
  Loader2,
  MapPin,
  Navigation,
  Phone,
  Search,
} from 'lucide-react'

function formatDistance(meters) {
  if (typeof meters !== 'number') return ''

  if (meters >= 1000) {
    return `${(meters / 1000).toFixed(1)} km`
  }

  return `${meters} m`
}

export default function HospitalFinder({
  departments = [],
  location = '',
  onLocationChange,
  hospitals = [],
  onHospitalsChange,
  notice = '',
  onNoticeChange,
}) {
  const [department, setDepartment] = useState('')
  const [coords, setCoords] = useState(null)
  const [accuracy, setAccuracy] = useState(null)
  const [radius, setRadius] = useState(5000)
  const [loading, setLoading] = useState(false)
  const [detecting, setDetecting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!department && departments.length > 0) {
      setDepartment(departments[0])
    }
  }, [department, departments])

  async function runSearch(nextCoords = coords) {
    const selected = department.trim()

    if (!selected) {
      setError('먼저 진료과를 입력해 주세요.')
      return
    }

    if (!nextCoords && !location.trim()) {
      setError(
        '현재 위치를 선택하거나 지역명을 입력해 주세요.'
      )
      return
    }

    setLoading(true)
    setError('')

    try {
      const payload = {
        departments: [selected],
        location: nextCoords ? '' : location.trim(),
        radius,
      }

      if (nextCoords) {
        payload.latitude = nextCoords.latitude
        payload.longitude = nextCoords.longitude
      }

      const response = await fetch('/api/hospitals', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      })

      const data = await response.json().catch(
        () => ({})
      )

      if (!response.ok) {
        throw new Error(
          typeof data.detail === 'string'
            ? data.detail
            : '병원 검색에 실패했습니다.'
        )
      }

      onHospitalsChange(data.hospitals || [])
      onNoticeChange(data.notice || '')
    } catch (err) {
      onHospitalsChange([])
      onNoticeChange('')
      setError(
        err.message || '병원 검색 중 오류가 발생했습니다.'
      )
    } finally {
      setLoading(false)
    }
  }

  function handleCurrentLocation() {
    if (!navigator.geolocation) {
      setError(
        '현재 브라우저에서 위치 확인을 지원하지 않습니다.'
      )
      return
    }

    if (!window.isSecureContext) {
      setError(
        '현재 위치 기능은 HTTPS 또는 localhost에서 사용할 수 있습니다.'
      )
      return
    }

    setDetecting(true)
    setError('')

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const point = {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        }

        setCoords(point)
        setAccuracy(position.coords.accuracy)
        onLocationChange('')
        onHospitalsChange([])
        onNoticeChange('')
        setDetecting(false)

        if (department.trim()) {
          runSearch(point)
        } else {
          setError(
            '위치를 확인했습니다. 진료과를 선택해 주세요.'
          )
        }
      },
      (geoError) => {
        setDetecting(false)

        if (geoError.code === 1) {
          setError(
            '위치 권한이 거부되었습니다. 지역명을 직접 입력해 주세요.'
          )
        } else if (geoError.code === 3) {
          setError(
            '위치 확인 시간이 초과되었습니다. 다시 시도하거나 지역명을 입력해 주세요.'
          )
        } else {
          setError(
            '현재 위치를 확인하지 못했습니다. 지역명을 직접 입력해 주세요.'
          )
        }
      },
      {
        enableHighAccuracy: false,
        timeout: 10000,
        maximumAge: 0,
      }
    )
  }

  function handleRegionChange(event) {
    setCoords(null)
    setAccuracy(null)
    setError('')
    onLocationChange(event.target.value)
    onHospitalsChange([])
    onNoticeChange('')
  }

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 space-y-3">
        <div>
          <div className="mb-1.5 flex items-center gap-1.5 text-xs font-bold text-slate-700">
            <Building2 className="h-3.5 w-3.5 text-sky-700" />
            진료과 선택
          </div>

          {departments.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {departments.map((item, index) => (
                <button
                  key={`${item}-${index}`}
                  type="button"
                  onClick={() => setDepartment(item)}
                  className={`rounded-md border px-2 py-1 text-[11px] ${
                    department === item
                      ? 'border-sky-500 bg-sky-100 text-sky-800'
                      : 'border-slate-200 bg-white text-slate-600'
                  }`}
                >
                  {item}
                </button>
              ))}
            </div>
          )}

          <input
            type="text"
            value={department}
            onChange={(event) => {
              setDepartment(event.target.value)
              onHospitalsChange([])
              onNoticeChange('')
            }}
            maxLength={40}
            placeholder="예: 내과, 정형외과, 피부과"
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs outline-none focus:border-sky-500"
          />

          <p className="mt-1 text-[11px] text-slate-500">
            분석에서 추천된 진료과를 선택하거나 직접 입력할 수 있습니다.
          </p>
        </div>

        <div>
          <div className="mb-1.5 flex items-center gap-1.5 text-xs font-bold text-slate-700">
            <MapPin className="h-3.5 w-3.5 text-sky-700" />
            검색 위치
          </div>

          <button
            type="button"
            onClick={handleCurrentLocation}
            disabled={detecting || loading}
            className="mb-2 flex w-full items-center justify-center gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs font-semibold text-sky-800 hover:bg-sky-100 disabled:opacity-50"
          >
            {detecting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Navigation className="h-4 w-4" />
            )}
            {detecting ? '현재 위치 확인 중...' : '내 위치로 검색'}
          </button>

          {coords && (
            <div className="mb-2 rounded-lg border border-emerald-200 bg-emerald-50 px-2.5 py-2 text-[11px] text-emerald-800">
              브라우저 위치를 사용합니다.
              {Number.isFinite(accuracy) && (
                <span>
                  {' '}
                  (표시 정확도 약 {Math.round(accuracy)}m)
                </span>
              )}
            </div>
          )}

          <form
            onSubmit={(event) => {
              event.preventDefault()
              runSearch()
            }}
            className="space-y-2"
          >
            <input
              type="text"
              value={location}
              onChange={handleRegionChange}
              maxLength={70}
              placeholder="또는 지역 입력: 서울 종로구"
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs outline-none focus:border-sky-500"
            />

            <div className="flex items-center gap-2">
              <label
                htmlFor="hospital-radius"
                className="shrink-0 text-[11px] text-slate-600"
              >
                검색 반경
              </label>

              <select
                id="hospital-radius"
                value={radius}
                onChange={(event) => {
                  setRadius(Number(event.target.value))
                  onHospitalsChange([])
                }}
                disabled={!coords}
                className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs disabled:opacity-40"
              >
                <option value={3000}>3 km</option>
                <option value={5000}>5 km</option>
                <option value={10000}>10 km</option>
                <option value={20000}>20 km</option>
              </select>

              <button
                type="submit"
                disabled={loading || detecting}
                className="flex items-center gap-1.5 rounded-lg bg-sky-700 px-3 py-2 text-xs font-semibold text-white hover:bg-sky-800 disabled:opacity-50"
              >
                {loading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Search className="h-3.5 w-3.5" />
                )}
                검색
              </button>
            </div>
          </form>

          <p className="text-[11px] text-slate-500">
            지역명 검색에서는 검색 반경과 거리순 정렬을 적용하지 않습니다.
          </p>
        </div>
      </div>

      {error && (
        <p
          role="alert"
          className="rounded-lg border border-rose-200 bg-rose-50 p-2.5 text-xs text-rose-700"
        >
          {error}
        </p>
      )}

      {notice && (
        <p className="rounded-lg bg-slate-100 p-2.5 text-[11px] leading-relaxed text-slate-600">
          {notice}
        </p>
      )}

      {loading && (
        <div className="flex items-center justify-center gap-2 py-6 text-xs text-sky-700">
          <Loader2 className="h-4 w-4 animate-spin" />
          실제 병원 정보를 검색하고 있습니다...
        </div>
      )}

      {!loading && hospitals.length > 0 && (
        <div className="space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-800">
              검색 결과 {hospitals.length}곳
            </span>
            <span className="text-[10px] text-slate-500">
              카카오 로컬 API
            </span>
          </div>

          {hospitals.map((hospital, index) => {
            const isKakaoLink =
              hospital.url?.startsWith(
                'https://place.map.kakao.com/'
              )

            const phone = (hospital.phone || '').replace(
              /[^0-9+]/g,
              ''
            )

            return (
              <div
                key={hospital.id || index}
                className="space-y-1.5 rounded-xl border border-slate-200 bg-white p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 text-xs font-bold text-slate-900">
                    {hospital.name}
                  </div>

                  {typeof hospital.distance_m === 'number' && (
                    <span className="shrink-0 rounded-md bg-sky-50 px-1.5 py-0.5 text-[11px] font-semibold text-sky-700">
                      {formatDistance(hospital.distance_m)}
                    </span>
                  )}
                </div>

                <div className="text-[11px] text-sky-700">
                  검색 기준: {hospital.department}
                </div>

                {hospital.category && (
                  <div className="text-[10px] text-slate-500">
                    {hospital.category}
                  </div>
                )}

                {hospital.address && (
                  <p className="text-[11px] leading-relaxed text-slate-700">
                    <MapPin className="mr-1 inline h-3 w-3" />
                    {hospital.address}
                  </p>
                )}

                {phone && (
                  <a
                    href={`tel:${phone}`}
                    className="inline-flex items-center gap-1 text-[11px] text-slate-600 hover:text-sky-700"
                  >
                    <Phone className="h-3 w-3" />
                    {hospital.phone}
                  </a>
                )}

                {isKakaoLink && (
                  <a
                    href={hospital.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center justify-center gap-1.5 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-[11px] font-semibold text-sky-800 hover:bg-sky-100"
                  >
                    카카오맵에서 위치 확인
                    <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>
            )
          })}

          <p className="text-[11px] leading-relaxed text-slate-500">
            검색어와 장소 카테고리로 찾은 의료기관입니다.
            특정 진료과 운영 여부, 전문의 유무 및 현재 진료 가능 여부를
            보증하지 않습니다.
          </p>
        </div>
      )}

      {!loading && hospitals.length === 0 && !error && (
        <p className="py-5 text-center text-xs text-slate-500">
          진료과와 위치를 선택해 병원을 검색해 주세요.
        </p>
      )}
    </div>
  )
}