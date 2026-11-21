
import React, { useEffect, useRef, useState } from 'react'
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { PDFDocument } from 'pdf-lib'
import {
  Download, Eraser, FileText, Loader2,
  RotateCcw, RotateCw, ShieldCheck, Upload, X,
} from 'lucide-react'

GlobalWorkerOptions.workerSrc = pdfWorkerUrl

const MAX_BYTES = 12 * 1024 * 1024
const MAX_PAGES = 10
const MAX_PIXELS = 18_000_000
const PDF_SCALE = 1.5
const SUPPORTED = /\.(pdf|png|jpe?g|webp)$/i
const clamp = (n) => Math.min(1, Math.max(0, n))

function toBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => blob
        ? resolve(blob)
        : reject(new Error('이미지 생성 실패')),
      'image/png',
    )
  })
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () =>
      reject(new Error('이미지를 읽을 수 없습니다.'))
    image.src = url
  })
}

function rectangle(a, b) {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    width: Math.abs(a.x - b.x),
    height: Math.abs(a.y - b.y),
  }
}

function copyMasks(masks) {
  return Object.fromEntries(
    Object.entries(masks).map(([key, boxes]) => [
      key,
      boxes.map((box) => ({ ...box })),
    ]),
  )
}

// 회전 시 기존 마스킹 영역도 동일한 방향으로 회전한다.
function rotateMasks(boxes, clockwise) {
  return boxes.map((box) => clockwise
    ? {
        x: clamp(1 - box.y - box.height),
        y: box.x,
        width: box.height,
        height: box.width,
      }
    : {
        x: box.y,
        y: clamp(1 - box.x - box.width),
        width: box.height,
        height: box.width,
      })
}

// CSS 회전이 아닌 실제 이미지 픽셀 회전.
async function rotatePage(page, turns) {
  const normalized = ((turns % 4) + 4) % 4
  if (normalized === 0) return page

  const image = await loadImage(page.url)
  const sideways = normalized % 2 === 1
  const canvas = document.createElement('canvas')

  canvas.width = sideways ? page.height : page.width
  canvas.height = sideways ? page.width : page.height

  const ctx = canvas.getContext('2d', { alpha: false })
  if (!ctx) {
    throw new Error('회전용 Canvas를 만들 수 없습니다.')
  }

  ctx.fillStyle = '#fff'
  ctx.fillRect(0, 0, canvas.width, canvas.height)

  if (normalized === 1) {
    ctx.translate(page.height, 0)
    ctx.rotate(Math.PI / 2)
  } else if (normalized === 2) {
    ctx.translate(page.width, page.height)
    ctx.rotate(Math.PI)
  } else {
    ctx.translate(0, page.width)
    ctx.rotate(-Math.PI / 2)
  }

  ctx.drawImage(image, 0, 0, page.width, page.height)

  const blob = await toBlob(canvas)
  const rotated = {
    ...page,
    url: URL.createObjectURL(blob),
    width: canvas.width,
    height: canvas.height,
    pdfWidth: sideways && page.pdfWidth
      ? page.pdfHeight
      : page.pdfWidth,
    pdfHeight: sideways && page.pdfHeight
      ? page.pdfWidth
      : page.pdfHeight,
  }

  canvas.width = 0
  canvas.height = 0
  return rotated
}

// 실제 이미지 픽셀에 마스킹 적용.
// PDF로 변환할 때 원본 텍스트 레이어는 포함되지 않는다.
async function maskedPng(page, boxes) {
  const image = await loadImage(page.url)
  const canvas = document.createElement('canvas')

  canvas.width = page.width
  canvas.height = page.height

  const ctx = canvas.getContext('2d', { alpha: false })
  if (!ctx) {
    throw new Error('마스킹용 Canvas를 만들 수 없습니다.')
  }

  ctx.fillStyle = '#fff'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height)

  ctx.fillStyle = '#000'
  boxes.forEach((box) => {
    const x1 = Math.floor(box.x * canvas.width)
    const y1 = Math.floor(box.y * canvas.height)
    const x2 = Math.ceil(
      (box.x + box.width) * canvas.width,
    )
    const y2 = Math.ceil(
      (box.y + box.height) * canvas.height,
    )
    ctx.fillRect(x1, y1, x2 - x1, y2 - y1)
  })

  const blob = await toBlob(canvas)
  canvas.width = 0
  canvas.height = 0
  return blob
}

export default function SecureDocumentUpload({
  onFileReady,
  uploadedFileName,
  inputRef,
  reopenRequestToken = 0,
  processing = false,
}) {
  const [sourceFile, setSourceFile] = useState(null)
  const [pages, setPages] = useState([])
  const [masks, setMasks] = useState({})
  const [rotations, setRotations] = useState({})
  const [pageIndex, setPageIndex] = useState(0)
  const [draft, setDraft] = useState(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const urlsRef = useRef([])
  const runRef = useRef(0)
  const drawingRef = useRef(null)
  const operationRef = useRef(false)

  // 이전 원본과 편집 정보는 브라우저 메모리에만 보관.
  const committedRef = useRef(null)
  const reopenTokenRef = useRef(reopenRequestToken)

  const page = pages[pageIndex]
  const pageMasks = masks[pageIndex] || []
  const maskCount = Object.values(masks).reduce(
    (count, list) => count + list.length,
    0,
  )
  const locked = Boolean(busy) || processing

  function clearUrls() {
    urlsRef.current.forEach((url) => {
      URL.revokeObjectURL(url)
    })
    urlsRef.current = []
  }

  useEffect(() => () => {
    runRef.current += 1
    clearUrls()
  }, [])

  function closeEditor() {
    runRef.current += 1
    clearUrls()

    setSourceFile(null)
    setPages([])
    setMasks({})
    setRotations({})
    setPageIndex(0)
    setDraft(null)
    setBusy('')
    setError('')

    drawingRef.current = null
  }

  async function openFile(file, previous = null) {
    if (!file || processing || operationRef.current) return

    const runId = ++runRef.current
    clearUrls()

    setSourceFile(file)
    setPages([])
    setMasks({})
    setRotations({})
    setPageIndex(0)
    setDraft(null)
    setError('')
    setBusy('문서를 브라우저에서 준비 중입니다...')

    const created = []
    let active = false

    try {
      if (!SUPPORTED.test(file.name)) {
        throw new Error(
          'PDF, PNG, JPG, JPEG, WEBP만 지원합니다.',
        )
      }

      if (file.size === 0 || file.size > MAX_BYTES) {
        throw new Error(
          '파일은 12MB 이하의 비어 있지 않은 파일이어야 합니다.',
        )
      }

      const next = []

      if (/\.pdf$/i.test(file.name)) {
        const task = getDocument({
          data: new Uint8Array(await file.arrayBuffer()),
          isEvalSupported: false,
        })

        let pdf = null

        try {
          pdf = await task.promise

          if (pdf.numPages < 1 || pdf.numPages > MAX_PAGES) {
            throw new Error(
              `PDF는 최대 ${MAX_PAGES}페이지를 지원합니다.`,
            )
          }

          for (let i = 1; i <= pdf.numPages; i += 1) {
            if (runRef.current !== runId) return

            setBusy(
              `${i}/${pdf.numPages}페이지 렌더링 중...`,
            )

            const pdfPage = await pdf.getPage(i)

            try {
              const unit = pdfPage.getViewport({ scale: 1 })
              const viewport = pdfPage.getViewport({
                scale: PDF_SCALE,
              })

              const width = Math.ceil(viewport.width)
              const height = Math.ceil(viewport.height)

              if (width * height > MAX_PIXELS) {
                throw new Error(
                  'PDF 페이지 해상도 제한 초과',
                )
              }

              const canvas = document.createElement('canvas')
              canvas.width = width
              canvas.height = height

              await pdfPage.render({
                canvasContext: canvas.getContext('2d'),
                viewport,
              }).promise

              const blob = await toBlob(canvas)
              canvas.width = 0
              canvas.height = 0

              const url = URL.createObjectURL(blob)
              created.push(url)

              next.push({
                url,
                width,
                height,
                pdfWidth: unit.width,
                pdfHeight: unit.height,
              })
            } finally {
              pdfPage.cleanup()
            }
          }
        } finally {
          if (pdf) {
            await pdf.destroy()
          } else {
            await task.destroy().catch(() => {})
          }
        }
      } else {
        const url = URL.createObjectURL(file)
        created.push(url)

        const img = await loadImage(url)

        if (
          img.naturalWidth * img.naturalHeight > MAX_PIXELS
        ) {
          throw new Error('이미지 해상도 제한 초과')
        }

        next.push({
          url,
          width: img.naturalWidth,
          height: img.naturalHeight,
        })
      }

      // 이전 편집 상태에서 재시작한 경우
      // 페이지별 회전 방향과 마스킹 영역을 복원.
      const restoredRotations = previous?.rotations || {}

      for (let index = 0; index < next.length; index += 1) {
        if (runRef.current !== runId) return

        const turns = Number(
          restoredRotations[index] || 0,
        ) % 4

        if (turns) {
          const rotated = await rotatePage(
            next[index],
            turns,
          )

          created.push(rotated.url)
          next[index] = rotated
        }
      }

      if (runRef.current !== runId) return

      urlsRef.current = created
      active = true

      setPages(next)
      setMasks(copyMasks(previous?.masks || {}))
      setRotations({ ...restoredRotations })
    } catch (e) {
      if (runRef.current === runId) {
        setError(
          e.message || '파일을 열지 못했습니다.',
        )
      }
    } finally {
      if (!active) {
        created.forEach((url) => {
          URL.revokeObjectURL(url)
        })
      }

      if (runRef.current === runId) {
        setBusy('')
      }
    }
  }

  // 이전에 업로드했던 파일의 원본으로 재편집.
  function reopen() {
    if (
      locked ||
      sourceFile ||
      !committedRef.current
    ) return

    const previous = committedRef.current

    void openFile(previous.file, previous)
  }

  // 결과 뷰어에서 들어오는 재마스킹 요청.
  useEffect(() => {
    if (
      reopenTokenRef.current === reopenRequestToken
    ) return

    reopenTokenRef.current = reopenRequestToken
    reopen()
  }, [reopenRequestToken])

  // 현재 페이지 회전 및 마스킹 영역 좌표 변환.
  async function rotate(clockwise) {
    if (
      !page ||
      locked ||
      operationRef.current
    ) return

    operationRef.current = true

    const current = pageIndex
    drawingRef.current = null

    setDraft(null)
    setError('')
    setBusy(
      clockwise
        ? '오른쪽 90° 회전 중...'
        : '왼쪽 90° 회전 중...',
    )

    try {
      const nextPage = await rotatePage(
        page,
        clockwise ? 1 : 3,
      )

      urlsRef.current.push(nextPage.url)

      setPages((prev) =>
        prev.map((entry, index) =>
          index === current ? nextPage : entry,
        ),
      )

      setMasks((prev) => ({
        ...prev,
        [current]: rotateMasks(
          prev[current] || [],
          clockwise,
        ),
      }))

      setRotations((prev) => ({
        ...prev,
        [current]:
          ((prev[current] || 0) + (clockwise ? 1 : 3)) % 4,
      }))
    } catch (e) {
      setError(
        e.message || '페이지 회전에 실패했습니다.',
      )
    } finally {
      operationRef.current = false
      setBusy('')
    }
  }

  function point(event) {
    const bounds =
      event.currentTarget.getBoundingClientRect()

    return {
      x: clamp(
        (event.clientX - bounds.left) / bounds.width,
      ),
      y: clamp(
        (event.clientY - bounds.top) / bounds.height,
      ),
    }
  }

  function startDraw(event) {
    if (
      locked ||
      !page ||
      event.button !== 0
    ) return

    event.preventDefault()

    event.currentTarget.setPointerCapture(
      event.pointerId,
    )

    const start = point(event)

    drawingRef.current = {
      start,
      index: pageIndex,
    }

    setDraft(rectangle(start, start))
  }

  function moveDraw(event) {
    if (!drawingRef.current) return

    setDraft(
      rectangle(
        drawingRef.current.start,
        point(event),
      ),
    )
  }

  function endDraw(event) {
    if (!drawingRef.current) return

    const {
      start,
      index,
    } = drawingRef.current

    drawingRef.current = null
    setDraft(null)

    const box = rectangle(start, point(event))

    if (
      box.width < 0.002 ||
      box.height < 0.002
    ) return

    setMasks((prev) => ({
      ...prev,
      [index]: [
        ...(prev[index] || []),
        box,
      ],
    }))
  }

  // PDF는 각 페이지를 회전·마스킹한 이미지로 재구성.
  async function makeFile() {
    if (
      !sourceFile ||
      pages.length === 0
    ) {
      throw new Error(
        '문서가 준비되지 않았습니다.',
      )
    }

    const stem =
      sourceFile.name.replace(/\.[^.]+$/, '')

    if (/\.pdf$/i.test(sourceFile.name)) {
      const output = await PDFDocument.create()

      for (let i = 0; i < pages.length; i += 1) {
        setBusy(
          `${i + 1}/${pages.length}페이지 파일 생성 중...`,
        )

        const blob = await maskedPng(
          pages[i],
          masks[i] || [],
        )

        const image = await output.embedPng(
          await blob.arrayBuffer(),
        )

        const pdfPage = output.addPage([
          pages[i].pdfWidth,
          pages[i].pdfHeight,
        ])

        pdfPage.drawImage(image, {
          x: 0,
          y: 0,
          width: pdfPage.getWidth(),
          height: pdfPage.getHeight(),
        })
      }

      const bytes = await output.save()

      if (bytes.length > MAX_BYTES) {
        throw new Error(
          '생성된 PDF가 12MB를 초과했습니다. 문서를 나누어 주세요.',
        )
      }

      return new File(
        [bytes],
        `${stem}_masked.pdf`,
        { type: 'application/pdf' },
      )
    }

    const blob = await maskedPng(
      pages[0],
      masks[0] || [],
    )

    if (blob.size > MAX_BYTES) {
      throw new Error(
        '생성된 이미지가 12MB를 초과했습니다.',
      )
    }

    return new File(
      [blob],
      `${stem}_masked.png`,
      { type: 'image/png' },
    )
  }

  async function confirm(downloadOnly = false) {
    if (
      locked ||
      operationRef.current ||
      !sourceFile
    ) return

    operationRef.current = true
    setError('')
    setBusy('마스킹 결과를 생성 중...')

    try {
      const file = await makeFile()

      if (downloadOnly) {
        const url = URL.createObjectURL(file)
        const a = document.createElement('a')

        a.href = url
        a.download = file.name

        document.body.appendChild(a)
        a.click()
        a.remove()

        setTimeout(() => {
          URL.revokeObjectURL(url)
        }, 30_000)
      } else {
        // 재편집에 사용할 원본과 편집 정보 보관.
        committedRef.current = {
          file: sourceFile,
          masks: copyMasks(masks),
          rotations: { ...rotations },
        }

        // 서버에는 수정된 파일만 전송.
        onFileReady(file)

        closeEditor()
      }
    } catch (e) {
      setError(
        e.message || '마스킹 파일 생성 실패',
      )
    } finally {
      operationRef.current = false
      setBusy('')
    }
  }

  return (
    <>
      {/* 업로드 영역 */}
      <div
        onClick={() => {
          if (!processing) {
            inputRef?.current?.click()
          }
        }}
        onDragOver={(event) => {
          event.preventDefault()
        }}
        onDrop={(event) => {
          event.preventDefault()

          if (!processing) {
            void openFile(
              event.dataTransfer.files?.[0],
            )
          }
        }}
        className={`rounded-xl border-2 border-dashed border-slate-300 p-4 text-center transition space-y-1.5 ${
          processing
            ? 'cursor-not-allowed opacity-50'
            : 'cursor-pointer hover:border-sky-500 hover:bg-sky-50/40'
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg,.webp"
          disabled={processing}
          className="hidden"
          onChange={(event) => {
            if (!processing) {
              void openFile(
                event.target.files?.[0],
              )
            }

            event.target.value = ''
          }}
        />

        <Upload className="mx-auto h-6 w-6 text-sky-700" />

        <div className="text-xs font-semibold text-slate-800">
          {uploadedFileName ||
            'PDF · 이미지 업로드 및 마스킹'}
        </div>

        <p className="text-[11px] text-slate-500">
          마스킹을 확정하기 전에는 원본 파일이 서버로 전송되지 않습니다.
        </p>
      </div>

      {/* 이전 마스킹 다시하기 */}
      {committedRef.current && !sourceFile && (
        <button
          type="button"
          disabled={processing}
          onClick={reopen}
          className="mt-2 flex w-full items-center justify-center gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs font-semibold text-sky-800 hover:bg-sky-100 disabled:opacity-40"
        >
          <RotateCcw className="h-4 w-4" />
          마스킹 다시하기
        </button>
      )}

      {/* 문서 편집 모달 */}
      {sourceFile && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/75 p-3 sm:p-6"
          role="dialog"
          aria-modal="true"
          aria-label="문서 마스킹 편집기"
        >
          <div className="flex max-h-[95vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">

            <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
                  <ShieldCheck className="h-4 w-4 text-emerald-700" />
                  선택 마스킹과 회전
                </div>

                <div className="truncate text-xs text-slate-500">
                  {sourceFile.name} · 선택 영역 {maskCount}개
                </div>
              </div>

              <button
                type="button"
                title="편집 취소"
                disabled={locked}
                onClick={closeEditor}
                className="rounded-lg p-2 hover:bg-slate-100 disabled:opacity-40"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* 마스킹 및 회전 도구 */}
            <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-slate-50 px-4 py-2 text-xs">

              <span className="inline-flex items-center gap-1">
                <Eraser className="h-3.5 w-3.5" />
                드래그로 가릴 영역을 선택
              </span>

              <button
                type="button"
                disabled={locked || !pageMasks.length}
                onClick={() => {
                  setMasks((prev) => ({
                    ...prev,
                    [pageIndex]: pageMasks.slice(0, -1),
                  }))
                }}
                className="ml-auto rounded border bg-white px-2 py-1 disabled:opacity-40"
              >
                한 단계 취소
              </button>

              <button
                type="button"
                disabled={locked || !pageMasks.length}
                onClick={() => {
                  setMasks((prev) => ({
                    ...prev,
                    [pageIndex]: [],
                  }))
                }}
                className="rounded border bg-white px-2 py-1 disabled:opacity-40"
              >
                현재 페이지 초기화
              </button>

              <button
                type="button"
                disabled={locked || !page}
                onClick={() => rotate(false)}
                className="inline-flex items-center gap-1 rounded border bg-white px-2 py-1 disabled:opacity-40"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                왼쪽 90°
              </button>

              <button
                type="button"
                disabled={locked || !page}
                onClick={() => rotate(true)}
                className="inline-flex items-center gap-1 rounded border bg-white px-2 py-1 disabled:opacity-40"
              >
                <RotateCw className="h-3.5 w-3.5" />
                오른쪽 90°
              </button>
            </div>

            {/* 페이지 이미지와 마스킹 오버레이 */}
            <div className="flex min-h-0 flex-1 items-start justify-center overflow-auto bg-slate-200 p-4">
              {busy && !page ? (
                <div className="flex items-center gap-2 py-8 text-sm text-slate-700">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {busy}
                </div>
              ) : page ? (
                <div
                  className="relative inline-block max-w-full shadow-xl"
                  style={{ lineHeight: 0 }}
                >
                  <img
                    src={page.url}
                    draggable={false}
                    alt={`${pageIndex + 1}페이지`}
                    className="block h-auto max-h-[65vh] w-auto max-w-full select-none"
                  />

                  <svg
                    viewBox="0 0 1000 1000"
                    preserveAspectRatio="none"
                    className="absolute inset-0 h-full w-full cursor-crosshair select-none"
                    style={{ touchAction: 'none' }}
                    onPointerDown={startDraw}
                    onPointerMove={moveDraw}
                    onPointerUp={endDraw}
                    onPointerCancel={() => {
                      drawingRef.current = null
                      setDraft(null)
                    }}
                  >
                    {pageMasks.map((box, index) => (
                      <rect
                        key={index}
                        x={box.x * 1000}
                        y={box.y * 1000}
                        width={box.width * 1000}
                        height={box.height * 1000}
                        fill="black"
                        stroke="#10b981"
                        strokeWidth="2"
                        vectorEffect="non-scaling-stroke"
                      />
                    ))}

                    {draft && (
                      <rect
                        x={draft.x * 1000}
                        y={draft.y * 1000}
                        width={draft.width * 1000}
                        height={draft.height * 1000}
                        fill="rgba(0,0,0,.65)"
                        stroke="#0ea5e9"
                        strokeWidth="2"
                        strokeDasharray="4 3"
                        vectorEffect="non-scaling-stroke"
                      />
                    )}
                  </svg>
                </div>
              ) : null}
            </div>

            {/* 하단 작업 버튼 */}
            <div className="space-y-2 border-t border-slate-200 px-4 py-3">

              {error && (
                <div
                  role="alert"
                  className="rounded bg-red-50 p-2 text-xs text-red-700"
                >
                  {error}
                </div>
              )}

              <p className="text-[11px] text-amber-800">
                회전은 OCR 입력에도 반영됩니다. PDF는 이미지 기반으로
                재생성되므로 텍스트 검색 기능이 사라집니다.
                업로드 전에 가린 내용을 확인하세요.
              </p>

              <div className="flex flex-wrap items-center justify-between gap-2">

                <div className="flex items-center gap-2 text-xs">
                  <button
                    type="button"
                    disabled={locked || pageIndex === 0}
                    onClick={() => {
                      setPageIndex((p) => p - 1)
                    }}
                    className="rounded border px-2 py-1.5 disabled:opacity-40"
                  >
                    이전
                  </button>

                  <span className="min-w-12 text-center">
                    {pages.length ? pageIndex + 1 : 0} / {pages.length}
                  </span>

                  <button
                    type="button"
                    disabled={
                      locked ||
                      pageIndex >= pages.length - 1
                    }
                    onClick={() => {
                      setPageIndex((p) => p + 1)
                    }}
                    className="rounded border px-2 py-1.5 disabled:opacity-40"
                  >
                    다음
                  </button>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    disabled={locked || !pages.length}
                    onClick={() => confirm(true)}
                    className="inline-flex items-center gap-1 rounded-lg border px-3 py-2 text-xs disabled:opacity-40"
                  >
                    <Download className="h-3.5 w-3.5" />
                    마스킹 파일 저장
                  </button>

                  <button
                    type="button"
                    disabled={locked || !pages.length}
                    onClick={() => confirm(false)}
                    className="inline-flex items-center gap-1 rounded-lg bg-sky-700 px-3 py-2 text-xs text-white disabled:opacity-40"
                  >
                    <FileText className="h-3.5 w-3.5" />
                    {busy || '확인 후 서버로 업로드'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
