import React, { useEffect, useState } from 'react'
import {
  ChevronLeft,
  ChevronRight,
  Eye,
  EyeOff,
  FileText,
  Loader2,
  RotateCcw,
  ShieldCheck,
  X,
  ZoomIn,
} from 'lucide-react'

/**
 * /api/preprocess 의 다중 페이지 응답(pages[])을 우선 사용한다.
 * 이전 버전 백엔드는 최상위 original_image, masked_image 만 응답하므로
 * 단일 페이지 폴백도 유지한다.
 */
function getResultPages(result) {
  if (Array.isArray(result?.pages) && result.pages.length > 0) {
    return result.pages
  }
  if (!result) return []
  if (!result.original_image && !result.masked_image) return []

  return [
    {
      page: 1,
      original_image: result.original_image,
      masked_image: result.masked_image,
      masked_count: result.masked_count ?? 0,
    },
  ]
}

/**
 * 기존 API는 페이지별 safe_text 를 pages 안에 싣지 않고,
 * [페이지 N] 헤더를 붙여 결합한 문자열로 반환한다.
 * 같은 문자열에서 선택된 페이지 부분만 표시한다.
 */
function getPageOcrText(safeText, pageNumber, totalPages) {
  const text = typeof safeText === 'string' ? safeText : ''
  if (!text.trim()) return ''

  const markers = [...text.matchAll(/^\[페이지\s+(\d+)\]\s*$/gm)]
  if (markers.length === 0) {
    return totalPages === 1 ? text.trim() : ''
  }

  const markerIndex = markers.findIndex((m) => Number(m[1]) === pageNumber)
  if (markerIndex === -1) return ''

  const start = markers[markerIndex].index + markers[markerIndex][0].length
  const end = markers[markerIndex + 1]?.index ?? text.length
  return text.slice(start, end).trim()
}

function PageNavigation({ pageIndex, pageCount, onPageChange }) {
  if (pageCount <= 1) return null

  return (
    <div className="flex items-center justify-center gap-2">
      <button
        type="button"
        onClick={() => onPageChange(pageIndex - 1)}
        disabled={pageIndex === 0}
        className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-35"
        aria-label="이전 페이지"
      >
        <ChevronLeft className="h-4 w-4" /> 이전
      </button>
      <span className="min-w-[66px] text-center text-xs font-semibold tabular-nums text-slate-700">
        {pageIndex + 1} / {pageCount}
      </span>
      <button
        type="button"
        onClick={() => onPageChange(pageIndex + 1)}
        disabled={pageIndex === pageCount - 1}
        className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-35"
        aria-label="다음 페이지"
      >
        다음 <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  )
}

export default function DocumentResultViewer({
  result,
  loading = false,
  viewMode = 'masked',
  onChangeViewMode,
  zoomOpen = false,
  onChangeZoomOpen,
  fallbackImageSrc = '',
  onRemask,
}) {
  const [pageIndex, setPageIndex] = useState(0)
  const [showOcrText, setShowOcrText] = useState(false)

  const pages = getResultPages(result)
  const pageCount = pages.length
  const currentIndex = Math.min(pageIndex, Math.max(0, pageCount - 1))
  const currentPage = pages[currentIndex]
  const pageNumber = Number(currentPage?.page) || currentIndex + 1
  const currentSrc =
    (viewMode === 'masked' ? currentPage?.masked_image : currentPage?.original_image) ||
    fallbackImageSrc ||
    ''
  const pageOcrText = getPageOcrText(result?.safe_text, pageNumber, pageCount)

  // /api/chat 은 검진 수치만 갱신할 수 있으므로 result 전체가 아니라
  // pages 배열과 safe_text 가 바뀔 때만 페이지 선택을 초기화한다.
  useEffect(() => {
    setPageIndex(0)
    setShowOcrText(false)
    onChangeZoomOpen?.(false)
  }, [result?.pages, result?.safe_text, onChangeZoomOpen])

  useEffect(() => {
    if (!zoomOpen) return undefined
    function handleKeyDown(event) {
      if (event.key === 'Escape') onChangeZoomOpen?.(false)
      if (event.key === 'ArrowLeft') setPageIndex((index) => Math.max(0, index - 1))
      if (event.key === 'ArrowRight') {
        setPageIndex((index) => Math.min(pageCount - 1, index + 1))
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [zoomOpen, pageCount, onChangeZoomOpen])

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white px-2.5 py-2">
        <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-0.5">
          <button
            type="button"
            onClick={() => onChangeViewMode?.('masked')}
            className={`rounded-md px-2.5 py-1 text-[11px] font-semibold transition ${
              viewMode === 'masked' ? 'bg-slate-900 text-white' : 'text-slate-600'
            }`}
          >
            마스킹 화면
          </button>
          <button
            type="button"
            onClick={() => onChangeViewMode?.('original')}
            className={`rounded-md px-2.5 py-1 text-[11px] font-semibold transition ${
              viewMode === 'original' ? 'bg-slate-700 text-white' : 'text-slate-600'
            }`}
          >
            원본 화면
          </button>
        </div>
        <div className="flex items-center gap-1.5">
          {pageCount > 0 && (
            <span className="text-[11px] font-medium text-slate-500">
              총 {pageCount}페이지
            </span>
          )}

          {currentSrc && !loading && typeof onRemask === 'function' && (
            <button
              type="button"
              onClick={onRemask}
              className="inline-flex items-center gap-1 rounded-lg border border-sky-200 bg-sky-50 px-2 py-1 text-[11px] font-semibold text-sky-800 hover:bg-sky-100"
              title="원본 문서의 마스킹을 다시 편집"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              마스킹 다시하기
            </button>
          )}

          {currentSrc && !loading && (
            <button
              type="button"
              onClick={() => onChangeZoomOpen?.(true)}
              className="rounded p-1 text-slate-500 hover:text-sky-700"
              title="현재 페이지 확대"
              aria-label="현재 페이지 확대"
            >
              <ZoomIn className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <div className="flex min-h-[210px] flex-col items-center justify-center gap-2 py-10 text-sky-700">
          <Loader2 className="h-6 w-6 animate-spin" />
          <span className="text-xs font-medium">문서 전체 페이지를 인식하고 마스킹하는 중입니다...</span>
        </div>
      ) : currentSrc ? (
        <>
          <div className="flex min-h-[210px] items-center justify-center p-2">
            <img
              src={currentSrc}
              alt={`${pageNumber}페이지 ${viewMode === 'masked' ? '마스킹 결과' : '원본'}`}
              className="max-h-[340px] w-full cursor-zoom-in rounded bg-white object-contain shadow-sm"
              onClick={() => onChangeZoomOpen?.(true)}
            />
          </div>
          <div className="space-y-2 border-t border-slate-200 bg-white px-3 py-2.5">
            <PageNavigation
              pageIndex={currentIndex}
              pageCount={pageCount}
              onPageChange={setPageIndex}
            />
            <div className="flex items-center justify-between gap-2 text-[11px] text-slate-500">
              <span className="inline-flex items-center gap-1">
                <ShieldCheck className="h-3.5 w-3.5 text-emerald-700" />
                {pageNumber}페이지 자동 마스킹 {currentPage?.masked_count ?? result?.masked_count ?? 0}건
              </span>
              <button
                type="button"
                onClick={() => setShowOcrText((value) => !value)}
                className="inline-flex items-center gap-1 font-semibold text-sky-700 hover:text-sky-900"
                aria-expanded={showOcrText}
              >
                {showOcrText ? <EyeOff className="h-3.5 w-3.5" /> : <FileText className="h-3.5 w-3.5" />}
                {showOcrText ? 'OCR 텍스트 접기' : '이 페이지 OCR 확인'}
              </button>
            </div>
            {showOcrText && (
              <div className="max-h-56 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-3">
                {pageOcrText ? (
                  <pre className="whitespace-pre-wrap break-words font-sans text-[11px] leading-5 text-slate-700">
                    {pageOcrText}
                  </pre>
                ) : (
                  <p className="text-xs text-slate-500">이 페이지에서 인식된 텍스트가 없습니다.</p>
                )}
              </div>
            )}
          </div>
        </>
      ) : (
        <div className="flex min-h-[210px] flex-col items-center justify-center gap-2 px-4 py-10 text-center">
          <Eye className="h-7 w-7 text-slate-300" />
          <p className="text-xs text-slate-400">
            결과지를 올리면 모든 페이지의 원본과 마스킹 결과를 확인할 수 있습니다.
          </p>
        </div>
      )}

      {zoomOpen && currentSrc && !loading && (
        <div
          className="fixed inset-0 z-[110] flex flex-col items-center justify-center gap-3 bg-slate-950/90 p-3 sm:p-5"
          role="dialog"
          aria-modal="true"
          aria-label={`${pageNumber}페이지 확대 보기`}
        >
          <div className="flex w-full max-w-6xl items-center justify-between gap-3 text-white">
            <span className="text-sm font-semibold">
              {viewMode === 'masked' ? '마스킹 화면' : '원본 화면'} · {pageNumber} / {pageCount}페이지
            </span>
            <button
              type="button"
              onClick={() => onChangeZoomOpen?.(false)}
              className="rounded-lg p-2 hover:bg-white/15"
              aria-label="확대 닫기"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
          <img
            src={currentSrc}
            alt={`${pageNumber}페이지 확대 이미지`}
            className="max-h-[75vh] max-w-full rounded bg-white object-contain"
          />
          <div className="rounded-lg bg-white p-1.5">
            <PageNavigation
              pageIndex={currentIndex}
              pageCount={pageCount}
              onPageChange={setPageIndex}
            />
          </div>
          <p className="text-center text-[11px] text-slate-300">키보드 ← / → 페이지 이동 · Esc 닫기</p>
        </div>
      )}
    </div>
  )
}
