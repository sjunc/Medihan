import React, { useEffect, useRef, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  BookOpen,
  Building2,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Download,
  Eye,
  FileImage,
  FileSpreadsheet,
  FileText,
  HeartPulse,
  KeyRound,
  Landmark,
  Loader2,
  Lock,
  MapPin,
  Mic,
  MicOff,
  PanelRightClose,
  PanelRightOpen,
  Send,
  ShieldCheck,
  Sparkles,
  Upload,
  Volume2,
  VolumeX,
  X,
  ZoomIn,
} from 'lucide-react'
import SimpleMarkdown from './components/SimpleMarkdown'

const METRIC_LABELS = {
  systolic_bp: '수축기 혈압',
  diastolic_bp: '이완기 혈압',
  fasting_glucose: '공복혈당',
  total_cholesterol: '총콜레스테롤',
  ldl_cholesterol: 'LDL 콜레스테롤',
  hdl_cholesterol: 'HDL 콜레스테롤',
  triglycerides: '중성지방',
  ast: 'AST (SGOT)',
  alt: 'ALT (SGPT)',
  ggt: '감마지티피',
  egfr: 'eGFR',
  hemoglobin: '혈색소',
  bmi: '체질량지수(BMI)',
}

export default function App() {
  // 서비스 설정 상태
  const [healthInfo, setHealthInfo] = useState({ openai_configured: false, openai_key_preview: '' })
  const [apiModalOpen, setApiModalOpen] = useState(false)
  const [apiKeyInput, setApiKeyInput] = useState('')
  const [savingKey, setSavingKey] = useState(false)

  // 문서 업로드 & 마스킹 상태
  const [uploadedFile, setUploadedFile] = useState(null)
  const [maskOptions, setMaskOptions] = useState({
    mask_name: true,
    mask_rrn: true,
    mask_age: true,
    mask_contact: true,
  })
  const [preprocessResult, setPreprocessResult] = useState(null)
  const [viewMode, setViewMode] = useState('masked')
  const [preprocessing, setPreprocessing] = useState(false)
  const [zoomImageOpen, setZoomImageOpen] = useState(false)

  // 채팅 상태
  const [messages, setMessages] = useState([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        '안녕하세요, **메디한(Medihan)**입니다.\n\n' +
        '왼쪽에서 **진단서·소견서·건강검진 결과지(PDF 또는 이미지)**를 올리시면 민감한 개인정보를 먼저 가린 뒤 서류 내용을 쉽게 풀어드립니다.\n\n' +
        '결과지가 없더라도 아래 입력창에 **"공복혈당 128이고 혈압이 142/90인데 괜찮을까요?"**처럼 직접 수치를 입력하거나 검진 지원 제도를 물어보실 수 있습니다.',
      rag_sources: [],
      policy_results: null,
    },
  ])
  const [inputText, setInputText] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [latestEvaluations, setLatestEvaluations] = useState([])
  const [latestRagSources, setLatestRagSources] = useState([])
  const [latestSummary, setLatestSummary] = useState('')
  const [recommendedDepts, setRecommendedDepts] = useState([])
  const [openRefMsgId, setOpenRefMsgId] = useState(null)

  // 음성(TTS / STT)
  const [speakingMsgId, setSpeakingMsgId] = useState(null)
  const [listening, setListening] = useState(false)

  // 우측 사이드바 (기본 닫힘 -> 열릴 시 1/3 : 1/3 : 1/3)
  const [rightPanelOpen, setRightPanelOpen] = useState(false)
  const [rightTab, setRightTab] = useState('reports')
  const [location, setLocation] = useState('')
  const [hospitals, setHospitals] = useState([])
  const [hospitalNotice, setHospitalNotice] = useState('')
  const [reportFiles, setReportFiles] = useState({})
  const [exporting, setExporting] = useState(false)
  const [hospitalLoading, setHospitalLoading] = useState(false)

  const [errorBanner, setErrorBanner] = useState('')
  const fileInputRef = useRef(null)
  const chatEndRef = useRef(null)

  useEffect(() => {
    fetchHealth()
    return () => {
      if (typeof window !== 'undefined' && window.speechSynthesis) {
        window.speechSynthesis.cancel()
      }
    }
  }, [])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, chatLoading])

  async function fetchHealth() {
    try {
      const res = await fetch('/api/health')
      if (res.ok) {
        setHealthInfo(await res.json())
      }
    } catch {
      // ignore
    }
  }

  async function handleSaveApiKey(e) {
    e.preventDefault()
    setSavingKey(true)
    try {
      const res = await fetch('/api/SetApiKey', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: apiKeyInput }),
      })
      if (res.ok) {
        const data = await res.json()
        setHealthInfo(data)
        setApiModalOpen(false)
        setApiKeyInput('')
      }
    } catch (err) {
      setErrorBanner(`설정 저장 실패: ${err.message}`)
    } finally {
      setSavingKey(false)
    }
  }

  async function runPreprocess({ file = uploadedFile, options = maskOptions }) {
    if (!file) return
    setPreprocessing(true)
    setErrorBanner('')
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('mask_name', String(options.mask_name))
      form.append('mask_rrn', String(options.mask_rrn))
      form.append('mask_age', String(options.mask_age))
      form.append('mask_contact', String(options.mask_contact))

      const res = await fetch('/api/preprocess', { method: 'POST', body: form })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || '문서 인식에 실패했습니다.')
      }
      const data = await res.json()
      setPreprocessResult(data)
    } catch (err) {
      setErrorBanner(err.message)
    } finally {
      setPreprocessing(false)
    }
  }

  function handleFileChange(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploadedFile(file)
    setViewMode('masked')
    runPreprocess({ file, options: maskOptions })
  }

  function handleDrop(e) {
    e.preventDefault()
    const file = e.dataTransfer.files?.[0]
    if (!file) return
    setUploadedFile(file)
    setViewMode('masked')
    runPreprocess({ file, options: maskOptions })
  }

  function handleToggleMaskOption(key) {
    const updated = { ...maskOptions, [key]: !maskOptions[key] }
    setMaskOptions(updated)
    if (uploadedFile) {
      runPreprocess({ file: uploadedFile, options: updated })
    }
  }

  async function sendChat({ userMessage, actionType = 'auto' }) {
    if (chatLoading) return
    const trimmed = (userMessage || '').trim()
    if (!trimmed && actionType === 'auto') return

    setErrorBanner('')
    const displayMsg =
      trimmed ||
      (actionType === 'analyze'
        ? '업로드한 의료 서류를 알기 쉽게 설명해 주세요.'
        : actionType === 'hospital_recommend'
          ? '내 검진 결과에 맞는 진료과와 추천 병원을 알려주세요.'
          : '분석 결과를 보고서 파일로 저장해 주세요.')

    const userTurn = { id: `u_${Date.now()}`, role: 'user', content: displayMsg }
    const nextHistory = [...messages, userTurn]
    setMessages(nextHistory)
    setInputText('')
    setChatLoading(true)

    try {
      const historyPayload = nextHistory
        .filter((m) => m.id !== 'welcome')
        .map((m) => ({ role: m.role, content: m.content }))

      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_message: trimmed || displayMsg,
          action_type: actionType,
          location,
          gender: preprocessResult?.gender || 'unknown',
          metrics: preprocessResult?.metrics || {},
          safe_text: preprocessResult?.safe_text || '',
          chat_history: historyPayload,
        }),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || '답변 생성 중 오류가 발생했습니다.')
      }

      const data = await res.json()
      const assistantTurn = {
        id: `a_${Date.now()}`,
        role: 'assistant',
        content: data.assistant_reply,
        rag_sources: data.rag_sources || [],
        policy_results: data.policy_results || null,
        evaluations: data.evaluations || [],
      }
      setMessages((prev) => [...prev, assistantTurn])

      if (data.metrics && Object.keys(data.metrics).length > 0) {
        setPreprocessResult((prev) => ({
          ...(prev || {}),
          metrics: data.metrics,
        }))
      }
      if (data.evaluations?.length) setLatestEvaluations(data.evaluations)
      if (data.rag_sources?.length) setLatestRagSources(data.rag_sources)
      if (data.recommended_departments?.length) setRecommendedDepts(data.recommended_departments)
      if (data.assistant_reply) setLatestSummary(data.assistant_reply)

      if (data.hospitals?.length) setHospitals(data.hospitals)
      if (data.hospitals) setHospitalNotice(data.hospital_notice || '')
      if (data.report_files && Object.keys(data.report_files).length > 0) {
        setReportFiles(data.report_files)
      }
      if (data.open_right_panel) {
        setRightPanelOpen(true)
        setRightTab(data.right_panel_tab || 'reports')
      }
    } catch (err) {
      setErrorBanner(err.message)
    } finally {
      setChatLoading(false)
    }
  }

  async function handleGenerateReports(formats = ['docx', 'pdf', 'png']) {
    setExporting(true)
    setErrorBanner('')
    try {
      const res = await fetch('/api/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          metrics: preprocessResult?.metrics || {},
          gender: preprocessResult?.gender || 'unknown',
          summary_text: latestSummary,
          rag_sources: latestRagSources,
          hospitals,
          formats,
        }),
      })
      if (!res.ok) throw new Error('보고서 생성에 실패했습니다.')
      const data = await res.json()
      setReportFiles(data.files || {})
      setRightPanelOpen(true)
      setRightTab('reports')
    } catch (err) {
      setErrorBanner(err.message)
    } finally {
      setExporting(false)
    }
  }

  async function handleRefreshHospitals(nextLocation) {
    setLocation(nextLocation)
    if (!nextLocation.trim() || recommendedDepts.length === 0) return
    setHospitalLoading(true)
    try {
      const res = await fetch('/api/hospitals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          departments: recommendedDepts,
          location: nextLocation,
        }),
      })
      if (res.ok) {
        const data = await res.json()
        setHospitals(data.hospitals || [])
        setHospitalNotice(data.notice || '')
      }
    } catch {
      // ignore
    } finally {
      setHospitalLoading(false)
    }
  }

  function handleSpeak(msgId, text) {
    if (typeof window === 'undefined' || !window.speechSynthesis) {
      setErrorBanner('현재 브라우저는 음성 안내를 지원하지 않습니다.')
      return
    }
    window.speechSynthesis.cancel()
    if (speakingMsgId === msgId) {
      setSpeakingMsgId(null)
      return
    }
    const clean = text.replace(/[*#`•→]/g, ' ').replace(/https?:\/\/\S+/g, '')
    const utter = new SpeechSynthesisUtterance(clean)
    utter.lang = 'ko-KR'
    utter.rate = 0.96
    utter.onend = () => setSpeakingMsgId(null)
    utter.onerror = () => setSpeakingMsgId(null)
    setSpeakingMsgId(msgId)
    window.speechSynthesis.speak(utter)
  }

  function handleVoiceInput() {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRec) {
      setErrorBanner('음성 입력은 Chrome 등 지원 브라우저에서 사용할 수 있습니다.')
      return
    }
    const rec = new SpeechRec()
    rec.lang = 'ko-KR'
    rec.interimResults = false
    setListening(true)
    rec.onresult = (event) => {
      const transcript = event.results?.[0]?.[0]?.transcript || ''
      if (transcript) {
        setInputText((prev) => (prev ? `${prev} ${transcript}` : transcript))
      }
      setListening(false)
    }
    rec.onerror = () => setListening(false)
    rec.onend = () => setListening(false)
    rec.start()
  }

  const activeImageSrc =
    preprocessResult && (viewMode === 'masked' ? preprocessResult.masked_image : preprocessResult.original_image)

  return (
    <div className="h-screen flex flex-col bg-slate-100 text-slate-900 overflow-hidden">
      {/* 상단 심플 서비스 헤더 */}
      <header className="h-14 shrink-0 bg-white border-b border-slate-200 px-5 flex items-center justify-between gap-3 z-20">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl bg-sky-700 text-white flex items-center justify-center shadow-xs">
            <HeartPulse className="w-4.5 h-4.5" />
          </div>
          <div className="flex items-baseline gap-2">
            <h1 className="font-bold text-base tracking-tight text-slate-900">메디한</h1>
            <span className="text-xs text-slate-500 hidden sm:inline">내 손안의 의료 서류 해설 서비스</span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setApiModalOpen(true)}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border transition ${
              healthInfo.openai_configured
                ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                : 'bg-slate-50 border-slate-200 text-slate-600 hover:bg-slate-100'
            }`}
            title="AI 서비스 키 설정"
          >
            <KeyRound className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">{healthInfo.openai_configured ? 'AI 연결됨' : '설정'}</span>
          </button>

          <button
            type="button"
            onClick={() => setRightPanelOpen((v) => !v)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition ${
              rightPanelOpen
                ? 'bg-sky-700 border-sky-700 text-white'
                : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50'
            }`}
          >
            {rightPanelOpen ? <PanelRightClose className="w-3.5 h-3.5" /> : <PanelRightOpen className="w-3.5 h-3.5" />}
            <span>리포트 · 병원 안내</span>
          </button>
        </div>
      </header>

      {/* 에러 배너 */}
      {errorBanner && (
        <div className="bg-red-50 border-b border-red-200 px-4 py-2 text-xs text-red-700 flex items-center justify-between">
          <span className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            {errorBanner}
          </span>
          <button type="button" onClick={() => setErrorBanner('')} className="p-0.5 hover:bg-red-100 rounded">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* 메인 3-Pane 그리드: 기본 1/3 : 2/3, 우측 오픈 시 1/3 : 1/3 : 1/3 */}
      <main className="flex-1 grid grid-cols-1 md:grid-cols-3 min-h-0 overflow-hidden">
        {/* ================= LEFT PANE (항상 1/3) ================= */}
        <aside className="md:col-span-1 bg-white border-r border-slate-200 flex flex-col min-h-0">
          <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-emerald-600" />
              <h2 className="font-bold text-sm text-slate-800">의료 서류 업로드</h2>
            </div>
            {preprocessResult?.masked_count > 0 && (
              <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
                개인정보 {preprocessResult.masked_count}건 가림
              </span>
            )}
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {/* 파일 업로드 드롭존 */}
            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className="border-2 border-dashed border-slate-300 hover:border-sky-500 hover:bg-sky-50/40 rounded-xl p-4 text-center cursor-pointer transition space-y-1.5"
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,.webp"
                onChange={handleFileChange}
                className="hidden"
              />
              <Upload className="w-6 h-6 text-sky-700 mx-auto" />
              <div className="text-xs font-semibold text-slate-800">
                {uploadedFile ? uploadedFile.name : '진단서·검진 결과지 (PDF · 이미지) 선택'}
              </div>
              <p className="text-[11px] text-slate-500">파일을 끌어다 놓거나 클릭해 업로드하세요</p>
            </div>

            {/* 개인정보 마스킹 체크박스 */}
            <div className="bg-slate-50 rounded-xl p-3 border border-slate-200 space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-bold text-slate-700">
                <Lock className="w-3.5 h-3.5 text-slate-500" />
                <span>개인정보 자동 가림 항목</span>
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                {[
                  { key: 'mask_name', label: '이름' },
                  { key: 'mask_rrn', label: '주민등록번호' },
                  { key: 'mask_age', label: '생년월일 · 연령' },
                  { key: 'mask_contact', label: '연락처 · 주소' },
                ].map((opt) => (
                  <label
                    key={opt.key}
                    className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-white border border-slate-200 cursor-pointer hover:border-sky-400"
                  >
                    <input
                      type="checkbox"
                      checked={maskOptions[opt.key]}
                      onChange={() => handleToggleMaskOption(opt.key)}
                      className="rounded text-sky-700 focus:ring-sky-600"
                    />
                    <span className="text-xs text-slate-700">{opt.label}</span>
                  </label>
                ))}
              </div>
            </div>

            {/* 이미지 비교 프리뷰 */}
            <div className="border border-slate-200 rounded-xl overflow-hidden bg-slate-50">
              <div className="bg-white px-2.5 py-2 border-b border-slate-200 flex items-center justify-between">
                <div className="flex items-center gap-1 bg-slate-100 p-0.5 rounded-lg">
                  <button
                    type="button"
                    onClick={() => setViewMode('masked')}
                    className={`px-2.5 py-1 rounded-md text-[11px] font-semibold transition ${
                      viewMode === 'masked' ? 'bg-slate-900 text-white' : 'text-slate-600'
                    }`}
                  >
                    마스킹 화면
                  </button>
                  <button
                    type="button"
                    onClick={() => setViewMode('original')}
                    className={`px-2.5 py-1 rounded-md text-[11px] font-semibold transition ${
                      viewMode === 'original' ? 'bg-slate-700 text-white' : 'text-slate-600'
                    }`}
                  >
                    원본 화면
                  </button>
                </div>
                {activeImageSrc && (
                  <button
                    type="button"
                    onClick={() => setZoomImageOpen(true)}
                    className="p-1 text-slate-500 hover:text-sky-700 rounded"
                    title="크게 보기"
                  >
                    <ZoomIn className="w-4 h-4" />
                  </button>
                )}
              </div>

              <div className="min-h-[210px] flex items-center justify-center p-2">
                {preprocessing ? (
                  <div className="flex flex-col items-center gap-2 py-10 text-sky-700">
                    <Loader2 className="w-6 h-6 animate-spin" />
                    <span className="text-xs font-medium">문서를 읽고 개인정보를 가리는 중입니다...</span>
                  </div>
                ) : activeImageSrc ? (
                  <img
                    src={activeImageSrc}
                    alt="업로드된 의료 서류"
                    onClick={() => setZoomImageOpen(true)}
                    className="w-full max-h-[280px] object-contain rounded cursor-zoom-in bg-white shadow-xs"
                  />
                ) : (
                  <div className="text-center py-10 px-4 space-y-1.5">
                    <Eye className="w-7 h-7 text-slate-300 mx-auto" />
                    <p className="text-xs text-slate-400">결과지를 올리면 가림 처리된 화면을 확인할 수 있습니다.</p>
                  </div>
                )}
              </div>
            </div>

            {/* 인식된 건강검진 수치 */}
            {preprocessResult && (
              <div className="bg-sky-50/70 border border-sky-200 rounded-xl p-3">
                <div className="text-xs font-bold text-sky-900 mb-2">인식된 검진 수치</div>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(preprocessResult.metrics || {}).map(([k, v]) => (
                    <span
                      key={k}
                      className="text-[11px] bg-white border border-sky-200 text-slate-800 px-2 py-0.5 rounded-md font-medium"
                    >
                      {METRIC_LABELS[k] || k}: <b>{v}</b>
                    </span>
                  ))}
                  {Object.keys(preprocessResult.metrics || {}).length === 0 && (
                    <span className="text-[11px] text-slate-500">
                      인식된 수치가 없다면 채팅창에 직접 수치를 입력해 물어보실 수 있습니다.
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>

          <div className="p-3.5 border-t border-slate-200 bg-white">
            <button
              type="button"
              disabled={!preprocessResult || preprocessing || chatLoading}
              onClick={() => sendChat({ actionType: 'analyze' })}
              className="w-full py-2.5 px-3 rounded-xl bg-sky-700 hover:bg-sky-800 disabled:opacity-45 text-white text-xs font-bold flex items-center justify-center gap-2 shadow-xs transition cursor-pointer"
            >
              <Sparkles className="w-4 h-4" />
              <span>서류 분석하기</span>
            </button>
          </div>
        </aside>

        {/* ================= CENTER PANE (닫힘 시 2/3, 열림 시 1/3) ================= */}
        <section
          className={`${
            rightPanelOpen ? 'md:col-span-1' : 'md:col-span-2'
          } flex flex-col min-w-0 min-h-0 bg-slate-50`}
        >
          {/* 채팅 메시지 영역 */}
          <div className="flex-1 overflow-y-auto p-4 md:p-5 space-y-4">
            {messages.map((msg) => {
              const isUser = msg.role === 'user'
              return (
                <div key={msg.id} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className={`max-w-[88%] rounded-2xl px-4 py-3 shadow-xs ${
                      isUser
                        ? 'bg-sky-700 text-white rounded-br-sm'
                        : 'bg-white border border-slate-200 text-slate-800 rounded-bl-sm'
                    }`}
                  >
                    {!isUser && (
                      <div className="flex items-center justify-between gap-3 mb-2 pb-1.5 border-b border-slate-100">
                        <div className="flex items-center gap-1.5">
                          <Activity className="w-3.5 h-3.5 text-sky-700" />
                          <span className="text-xs font-bold text-slate-800">메디한</span>
                        </div>
                        <button
                          type="button"
                          onClick={() => handleSpeak(msg.id, msg.content)}
                          className={`flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium transition ${
                            speakingMsgId === msg.id
                              ? 'bg-amber-100 text-amber-800'
                              : 'bg-slate-100 hover:bg-sky-50 text-slate-600 hover:text-sky-700'
                          }`}
                        >
                          {speakingMsgId === msg.id ? (
                            <>
                              <VolumeX className="w-3.5 h-3.5" />
                              <span>정지</span>
                            </>
                          ) : (
                            <>
                              <Volume2 className="w-3.5 h-3.5" />
                              <span>음성 듣기</span>
                            </>
                          )}
                        </button>
                      </div>
                    )}

                    {isUser ? (
                      <p className="text-sm whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                    ) : (
                      <SimpleMarkdown content={msg.content} />
                    )}

                    {/* 판정 수치 칩 */}
                    {!isUser && msg.evaluations?.length > 0 && (
                      <div className="mt-3 pt-2.5 border-t border-slate-100 flex flex-wrap gap-1.5">
                        {msg.evaluations.map((ev) => (
                          <span
                            key={ev.key}
                            className={`text-[11px] font-semibold px-2 py-0.5 rounded-md border ${
                              ev.severity === 'high'
                                ? 'bg-red-50 text-red-700 border-red-200'
                                : ev.severity === 'warning'
                                  ? 'bg-amber-50 text-amber-800 border-amber-200'
                                  : 'bg-emerald-50 text-emerald-700 border-emerald-200'
                            }`}
                          >
                            {ev.item}: {ev.value} ({ev.status})
                          </span>
                        ))}
                      </div>
                    )}

                    {/* 관련 지원 제도 안내 박스 */}
                    {!isUser && msg.policy_results && (
                      <div className="mt-3 bg-emerald-50/70 border border-emerald-200 rounded-xl p-3 space-y-2">
                        <div className="flex items-center gap-1.5 text-xs font-bold text-emerald-900">
                          <Landmark className="w-4 h-4 text-emerald-700" />
                          <span>국가건강검진 · 지원 제도 안내</span>
                        </div>
                        {(msg.policy_results.rag_policies || []).map((pol) => (
                          <div key={pol.id} className="bg-white rounded-lg p-2.5 border border-emerald-100 text-xs">
                            <div className="font-bold text-slate-900">{pol.title}</div>
                            <div className="text-[11px] text-emerald-700 mb-1">출처: {pol.source}</div>
                            <p className="text-slate-700 whitespace-pre-line leading-relaxed">{pol.content}</p>
                          </div>
                        ))}
                        {(msg.policy_results.web_results || []).length > 0 && (
                          <div className="space-y-1">
                            {msg.policy_results.web_results.slice(0, 3).map((w, wIdx) => (
                              <a
                                key={wIdx}
                                href={w.url}
                                target="_blank"
                                rel="noreferrer"
                                className="block bg-white/80 hover:bg-white rounded-lg p-2 border border-emerald-100 text-[11px] transition"
                              >
                                <div className="font-semibold text-sky-800">{w.title}</div>
                                <div className="text-slate-600 line-clamp-2">{w.snippet}</div>
                              </a>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {/* 참고 의학 기준 아코디언 */}
                    {!isUser && msg.rag_sources?.length > 0 && (
                      <div className="mt-2.5">
                        <button
                          type="button"
                          onClick={() => setOpenRefMsgId(openRefMsgId === msg.id ? null : msg.id)}
                          className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-sky-700 hover:text-sky-900 bg-sky-50 px-2.5 py-1 rounded-lg border border-sky-200"
                        >
                          <BookOpen className="w-3.5 h-3.5" />
                          <span>참고 의학 기준 {msg.rag_sources.length}건</span>
                          {openRefMsgId === msg.id ? (
                            <ChevronUp className="w-3.5 h-3.5" />
                          ) : (
                            <ChevronDown className="w-3.5 h-3.5" />
                          )}
                        </button>
                        {openRefMsgId === msg.id && (
                          <div className="mt-2 space-y-2">
                            {msg.rag_sources.map((src) => (
                              <div key={src.id} className="bg-slate-50 border border-slate-200 rounded-lg p-2.5 text-xs">
                                <div className="font-bold text-slate-800">{src.title}</div>
                                <div className="text-[10.5px] text-slate-500 mb-1">출처: {src.source}</div>
                                <p className="text-slate-700 whitespace-pre-line leading-relaxed text-[11.5px]">
                                  {src.content}
                                </p>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}

            {chatLoading && (
              <div className="flex justify-start">
                <div className="bg-white border border-slate-200 rounded-2xl px-4 py-3 flex items-center gap-2 text-xs text-sky-800 shadow-xs">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>검진 기준과 의학 자료를 확인하여 답변을 작성하고 있습니다...</span>
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          {/* 하단 추천 질문 & 입력창 */}
          <div className="bg-white border-t border-slate-200 p-3 space-y-2.5">
            <div className="flex flex-wrap gap-1.5">
              <button
                type="button"
                disabled={chatLoading}
                onClick={() => sendChat({ userMessage: '핵심만 3줄로 쉽게 요약해 주세요.', actionType: 'auto' })}
                className="px-2.5 py-1 rounded-full bg-slate-100 hover:bg-sky-50 text-slate-700 hover:text-sky-800 border border-slate-200 text-xs font-medium transition"
              >
                핵심만 3줄 요약
              </button>
              <button
                type="button"
                disabled={chatLoading}
                onClick={() =>
                  sendChat({
                    userMessage: '제 서류와 관련된 국가건강검진·확진검사 지원 제도를 알려주세요.',
                    actionType: 'policy_search',
                  })
                }
                className="px-2.5 py-1 rounded-full bg-slate-100 hover:bg-emerald-50 text-slate-700 hover:text-emerald-800 border border-slate-200 text-xs font-medium transition"
              >
                확진검사 · 검진 지원 제도
              </button>
              <button
                type="button"
                disabled={chatLoading}
                onClick={() =>
                  sendChat({
                    userMessage: '제 서류 내용에 맞는 생활습관 관리 방법을 알려주세요.',
                    actionType: 'auto',
                  })
                }
                className="px-2.5 py-1 rounded-full bg-slate-100 hover:bg-sky-50 text-slate-700 hover:text-sky-800 border border-slate-200 text-xs font-medium transition"
              >
                맞춤 식단 · 생활관리
              </button>
              <button
                type="button"
                disabled={chatLoading}
                onClick={() => sendChat({ actionType: 'hospital_recommend' })}
                className="px-2.5 py-1 rounded-full bg-sky-50 hover:bg-sky-100 text-sky-800 border border-sky-200 text-xs font-semibold transition"
              >
                관련 진료과 · 병원 추천
              </button>
              <button
                type="button"
                disabled={chatLoading}
                onClick={() => sendChat({ actionType: 'export_report' })}
                className="px-2.5 py-1 rounded-full bg-sky-50 hover:bg-sky-100 text-sky-800 border border-sky-200 text-xs font-semibold transition"
              >
                결과 보고서 저장
              </button>
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault()
                sendChat({ userMessage: inputText, actionType: 'auto' })
              }}
              className="flex items-center gap-2"
            >
              <button
                type="button"
                onClick={handleVoiceInput}
                className={`p-2.5 rounded-xl border transition ${
                  listening
                    ? 'bg-red-50 border-red-300 text-red-600 animate-pulse'
                    : 'bg-slate-50 border-slate-200 text-slate-600 hover:bg-slate-100'
                }`}
                title="음성으로 질문하기"
              >
                {listening ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
              </button>
              <input
                type="text"
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                placeholder="궁금한 점이나 검진 수치를 직접 입력해 보세요..."
                className="flex-1 bg-slate-50 border border-slate-200 focus:border-sky-500 focus:bg-white rounded-xl px-3.5 py-2.5 text-sm outline-none transition"
              />
              <button
                type="submit"
                disabled={chatLoading || !inputText.trim()}
                className="px-4 py-2.5 rounded-xl bg-sky-700 hover:bg-sky-800 disabled:opacity-45 text-white font-semibold text-sm flex items-center gap-1.5 transition"
              >
                <Send className="w-4 h-4" />
                <span className="hidden sm:inline">전송</span>
              </button>
            </form>
          </div>
        </section>

        {/* ================= RIGHT PANE (열릴 시 1/3, 기본 닫힘) ================= */}
        {rightPanelOpen && (
          <aside className="md:col-span-1 bg-white border-l border-slate-200 flex flex-col min-h-0">
            <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between">
              <h2 className="font-bold text-sm text-slate-800">결과 보고서 및 병원 안내</h2>
              <button
                type="button"
                onClick={() => setRightPanelOpen(false)}
                className="p-1 rounded-lg hover:bg-slate-100 text-slate-500"
                title="닫기"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-2 p-2 gap-1 bg-slate-50 border-b border-slate-200">
              <button
                type="button"
                onClick={() => setRightTab('reports')}
                className={`py-1.5 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 transition ${
                  rightTab === 'reports' ? 'bg-white text-sky-800 shadow-xs' : 'text-slate-600'
                }`}
              >
                <FileText className="w-3.5 h-3.5" />
                <span>보고서 다운로드</span>
              </button>
              <button
                type="button"
                onClick={() => setRightTab('hospitals')}
                className={`py-1.5 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 transition ${
                  rightTab === 'hospitals' ? 'bg-white text-sky-800 shadow-xs' : 'text-slate-600'
                }`}
              >
                <Building2 className="w-3.5 h-3.5" />
                <span>추천 병원 찾기</span>
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {rightTab === 'reports' ? (
                <>
                  <div className="bg-slate-50 border border-slate-200 rounded-xl p-3 space-y-2">
                    <div className="text-xs font-bold text-slate-800 flex items-center justify-between">
                      <span>보고서 포함 항목</span>
                      <span className="text-[11px] font-normal text-slate-500">{latestEvaluations.length}개 항목</span>
                    </div>
                    {latestEvaluations.length > 0 ? (
                      <div className="space-y-1 max-h-40 overflow-y-auto">
                        {latestEvaluations.map((ev) => (
                          <div
                            key={ev.key}
                            className="flex items-center justify-between text-xs bg-white px-2.5 py-1.5 rounded-lg border border-slate-200"
                          >
                            <span className="font-medium text-slate-700">{ev.item}</span>
                            <div className="flex items-center gap-2">
                              <span className="font-bold text-slate-900">
                                {ev.value} {ev.unit}
                              </span>
                              <span
                                className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                                  ev.severity === 'high'
                                    ? 'bg-red-100 text-red-700'
                                    : ev.severity === 'warning'
                                      ? 'bg-amber-100 text-amber-800'
                                      : 'bg-emerald-100 text-emerald-700'
                                }`}
                              >
                                {ev.status}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-slate-500">
                        검진 결과 분석을 진행하면 수치와 해설이 보고서에 자동 반영됩니다.
                      </p>
                    )}
                  </div>

                  <button
                    type="button"
                    disabled={exporting}
                    onClick={() => handleGenerateReports(['docx', 'pdf', 'png'])}
                    className="w-full py-2.5 px-3 rounded-xl bg-sky-700 hover:bg-sky-800 disabled:opacity-50 text-white text-xs font-bold flex items-center justify-center gap-2 shadow-xs transition"
                  >
                    {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                    <span>Word · PDF · 이미지 보고서 만들기</span>
                  </button>

                  {Object.keys(reportFiles).length > 0 && (
                    <div className="space-y-2.5">
                      <div className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                        <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                        <span>생성된 파일 내려받기</span>
                      </div>

                      {reportFiles.docx && (
                        <a
                          href={reportFiles.docx.url}
                          download={reportFiles.docx.filename}
                          className="flex items-center justify-between p-3 rounded-xl border border-sky-200 bg-sky-50/70 hover:bg-sky-100 transition"
                        >
                          <div className="flex items-center gap-2.5">
                            <FileSpreadsheet className="w-5 h-5 text-sky-700" />
                            <div>
                              <div className="text-xs font-bold text-slate-900">Word 보고서 (.docx)</div>
                              <div className="text-[10.5px] text-slate-500">{reportFiles.docx.filename}</div>
                            </div>
                          </div>
                          <Download className="w-4 h-4 text-sky-700" />
                        </a>
                      )}

                      {reportFiles.pdf && (
                        <a
                          href={reportFiles.pdf.url}
                          download={reportFiles.pdf.filename}
                          className="flex items-center justify-between p-3 rounded-xl border border-rose-200 bg-rose-50/70 hover:bg-rose-100 transition"
                        >
                          <div className="flex items-center gap-2.5">
                            <FileText className="w-5 h-5 text-rose-700" />
                            <div>
                              <div className="text-xs font-bold text-slate-900">PDF 결과지 (.pdf)</div>
                              <div className="text-[10.5px] text-slate-500">{reportFiles.pdf.filename}</div>
                            </div>
                          </div>
                          <Download className="w-4 h-4 text-rose-700" />
                        </a>
                      )}

                      {reportFiles.png && (
                        <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-3 space-y-2">
                          <a
                            href={reportFiles.png.url}
                            download={reportFiles.png.filename}
                            className="flex items-center justify-between hover:opacity-80"
                          >
                            <div className="flex items-center gap-2.5">
                              <FileImage className="w-5 h-5 text-emerald-700" />
                              <div>
                                <div className="text-xs font-bold text-slate-900">요약 카드 이미지 (.png)</div>
                                <div className="text-[10.5px] text-slate-500">공유용 한눈에 보기 카드</div>
                              </div>
                            </div>
                            <Download className="w-4 h-4 text-emerald-700" />
                          </a>
                          <img
                            src={reportFiles.png.url}
                            alt="요약 카드 미리보기"
                            className="w-full rounded-lg border border-slate-200 shadow-xs"
                          />
                        </div>
                      )}
                    </div>
                  )}
                </>
              ) : (
                <>
                  <div className="space-y-2 bg-slate-50 p-3 rounded-xl border border-slate-200">
                    <label className="text-xs font-bold text-slate-700 flex items-center gap-1.5">
                      <MapPin className="w-3.5 h-3.5 text-sky-700" />
                      <span>진료 지역 입력</span>
                    </label>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={location}
                        onChange={(e) => setLocation(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleRefreshHospitals(location)
                        }}
                        placeholder="예: 서울 종로구, 부산 해운대구"
                        className="flex-1 text-xs bg-white border border-slate-200 rounded-lg px-2.5 py-2 outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => handleRefreshHospitals(location)}
                        className="px-3 py-2 rounded-lg bg-sky-700 text-white text-xs font-semibold hover:bg-sky-800"
                      >
                        검색
                      </button>
                    </div>
                    <div className="flex flex-wrap gap-1 pt-1">
                      <span className="text-[11px] text-slate-500">권장 진료과:</span>
                      {recommendedDepts.length === 0 && (
                        <span className="text-[11px] text-slate-500">서류 분석 후 표시됩니다</span>
                      )}
                      {recommendedDepts.map((dept) => (
                        <span
                          key={dept}
                          className="text-[11px] font-semibold bg-sky-100 text-sky-800 px-2 py-0.5 rounded"
                        >
                          {dept}
                        </span>
                      ))}
                    </div>
                  </div>

                  {hospitalLoading ? (
                    <div className="py-8 flex items-center justify-center gap-2 text-xs text-sky-700">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>추천 병원을 찾고 있습니다...</span>
                    </div>
                  ) : hospitals.length === 0 ? (
                    <div className="space-y-2">
                      {hospitalNotice && <p className="text-[11px] text-slate-600">{hospitalNotice}</p>}
                      <button
                        type="button"
                        disabled={!location.trim() || recommendedDepts.length === 0}
                        onClick={() => handleRefreshHospitals(location)}
                        className="w-full py-2.5 rounded-xl bg-sky-700 text-white text-xs font-bold disabled:opacity-40"
                      >
                        {recommendedDepts.length === 0 ? '서류 분석 후 병원을 검색할 수 있습니다' : '병원 검색하기'}
                      </button>
                    </div>
                  ) : (
                    <div className="space-y-2.5">
                      {hospitals.map((h, i) => (
                        <a
                          key={i}
                          href={h.url || undefined}
                          target="_blank"
                          rel="noreferrer"
                          className="block p-3 rounded-xl border border-slate-200 bg-white shadow-xs space-y-1.5 hover:bg-slate-50 transition"
                        >
                          <div className="font-bold text-xs text-slate-900">{h.name}</div>
                          <div className="text-[11px] font-semibold text-sky-700">{h.department}</div>
                          {h.reason && <p className="text-[11px] text-slate-700 bg-slate-50 p-2 rounded-lg line-clamp-3">{h.reason}</p>}
                        </a>
                      ))}
                      <p className="text-[11px] text-slate-500">웹 검색 결과입니다. 방문 전 병원에 진료 여부를 확인해 주세요.</p>
                    </div>
                  )}
                </>
              )}
            </div>
          </aside>
        )}
      </main>

      {/* 설정 (API 키) 모달 */}
      {apiModalOpen && (
        <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <form
            onSubmit={handleSaveApiKey}
            className="bg-white rounded-2xl max-w-md w-full p-5 shadow-xl border border-slate-200 space-y-4"
          >
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-base text-slate-900 flex items-center gap-2">
                <KeyRound className="w-4 h-4 text-sky-700" />
                <span>OpenAI API 키 설정</span>
              </h3>
              <button type="button" onClick={() => setApiModalOpen(false)} className="text-slate-400 hover:text-slate-700">
                <X className="w-5 h-5" />
              </button>
            </div>
            <p className="text-xs text-slate-600 leading-relaxed">
              입력하신 API 키는 상담 답변 및 의학 문서 임베딩 검색에 사용됩니다. 개인정보는 업로드 직후 가림 처리된 상태로만 분석됩니다.
            </p>
            <input
              type="password"
              value={apiKeyInput}
              onChange={(e) => setApiKeyInput(e.target.value)}
              placeholder="sk-proj-..."
              className="w-full px-3.5 py-2.5 text-sm border border-slate-300 rounded-xl focus:border-sky-500 outline-none"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setApiModalOpen(false)}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100"
              >
                취소
              </button>
              <button
                type="submit"
                disabled={savingKey}
                className="px-4 py-2 rounded-xl text-xs font-bold bg-sky-700 hover:bg-sky-800 text-white"
              >
                {savingKey ? '저장 중...' : '적용하기'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* 이미지 확대 모달 */}
      {zoomImageOpen && activeImageSrc && (
        <div
          onClick={() => setZoomImageOpen(false)}
          className="fixed inset-0 bg-slate-950/80 flex items-center justify-center z-50 p-6 cursor-zoom-out"
        >
          <img
            src={activeImageSrc}
            alt="확대 이미지"
            className="max-h-full max-w-full rounded-xl shadow-2xl bg-white"
          />
        </div>
      )}
    </div>
  )
}
