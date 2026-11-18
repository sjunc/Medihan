import React from 'react'

function renderInline(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((part, idx) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return (
        <strong key={idx} className="font-semibold text-slate-900">
          {part.slice(2, -2)}
        </strong>
      )
    }
    return <React.Fragment key={idx}>{part}</React.Fragment>
  })
}

export default function SimpleMarkdown({ content, largeText = false }) {
  if (!content) return null
  const lines = content.split('\n')

  return (
    <div className={`space-y-1.5 ${largeText ? 'text-[15.5px] leading-7' : 'text-[14px] leading-6'} text-slate-800`}>
      {lines.map((rawLine, idx) => {
        const line = rawLine.trimEnd()
        if (!line.trim()) {
          return <div key={idx} className="h-1" />
        }
        if (line.startsWith('### ')) {
          return (
            <h4 key={idx} className="font-bold text-slate-900 text-[15px] pt-1">
              {renderInline(line.slice(4))}
            </h4>
          )
        }
        if (line.startsWith('## ')) {
          return (
            <h3 key={idx} className="font-bold text-sky-900 text-[16px] pt-1">
              {renderInline(line.slice(3))}
            </h3>
          )
        }
        if (line.startsWith('- ') || line.startsWith('• ')) {
          return (
            <div key={idx} className="flex gap-2 pl-1">
              <span className="text-sky-600 font-bold select-none">•</span>
              <span className="flex-1">{renderInline(line.slice(2))}</span>
            </div>
          )
        }
        if (line.trim().startsWith('→')) {
          return (
            <div key={idx} className="pl-5 text-slate-600 text-[13.5px]">
              {renderInline(line.trim())}
            </div>
          )
        }
        return <p key={idx}>{renderInline(line)}</p>
      })}
    </div>
  )
}
