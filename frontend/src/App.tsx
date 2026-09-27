import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type ReactNode,
} from 'react'
import { getDocument, GlobalWorkerOptions, Util } from 'pdfjs-dist'
import pdfWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

type Screen =
  | 'home'
  | 'progress'
  | 'results'
  | 'viewer'
  | 'history'
  | 'placeholder'

type IconName =
  | 'home'
  | 'history'
  | 'reports'
  | 'settings'
  | 'help'
  | 'upload'
  | 'file'
  | 'remove'
  | 'spell'
  | 'link'
  | 'search'
  | 'arrow'
  | 'chevron'
  | 'check'
  | 'document'


type PageCountSource = 'client' | 'backend' | 'unavailable'

type NavigationItem = {
  label: string
  icon: IconName
}

type Feature = {
  id: string
  name: string
  description: string
  icon: IconName
}

type DocumentRecord = {
  name: string
  type: 'PDF' | 'DOCX'
  size: number
  pageCount: number | null
  pageCountSource: PageCountSource
}

type Finding = {
  id: number
  documentName: string
  documentId: string
  page: number
  featureId: string
  finding: string
  suggestion: string
  confidence?: number | null

  original?: string
  context?: string
  correctedSentence?: string
  paragraphIndex?: number
  boundingBox?: {
    x: number
    y: number
    width: number
    height: number
  }
}

type AnalysisResult = {
  document: DocumentRecord
  findings: Finding[]
  completedAt: string
}
type HistoryEntry = {
  id: string
  completedAt: string
  documents: string[]
  documentCount: number
  pageCount: number
  totalFindings: number
  spellCheckFindings: number
  brokenLinksFindings: number
  keywordSearchFindings: number
  result: AnalysisResult
}

const navigation: NavigationItem[] = [
  {
    label: 'Home',
    icon: 'home',
  },
  {
    label: 'History',
    icon: 'history',
  },
  {
    label: 'Reports',
    icon: 'reports',
  },
]

const secondaryNavigation: NavigationItem[] = [
  {
    label: 'Settings',
    icon: 'settings',
  },
  {
    label: 'Help',
    icon: 'help',
  },
]

// Future analysis checks and backend-supplied fields flow through these typed records.
const features: Feature[] = [
  {
    id: 'spell-check',
    name: 'Spell Check',
    description: 'Detect spelling errors and suggested corrections.',
    icon: 'spell',
  },
  {
    id: 'broken-links',
    name: 'Broken Links',
    description: 'Find invalid hyperlinks and document references.',
    icon: 'link',
  },
  {
    id: 'keyword-search',
    name: 'Keyword Search',
    description: 'Search for specific terms across the document.',
    icon: 'search',
  },
]
GlobalWorkerOptions.workerSrc = pdfWorker

function Icon({ name }: { name: IconName }) {
  const paths: Record<IconName, ReactNode> = {
    home: (
      <path d="m3 10 9-7 9 7v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-9Zm6 11v-6h6v6" />
    ),

    history: (
      <>
        <path d="M3 12a9 9 0 1 0 3-6.7" />
        <path d="M3 4v5h5M12 7v5l3 2" />
      </>
    ),

    reports: (
      <>
        <path d="M5 3h10a2 2 0 0 1 2 2v16H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" />
        <path d="M7 8h6M7 12h6M7 16h3" />
      </>
    ),

    settings: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.1 2.1-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.55V20h-3v-.09A1.7 1.7 0 0 0 10.7 18.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.1-2.1.06-.06A1.7 1.7 0 0 0 7.06 15a1.7 1.7 0 0 0-1.55-1.03H5v-3h.09A1.7 1.7 0 0 0 6.6 9.94a1.7 1.7 0 0 0-.34-1.88L6.2 8 8.3 5.9l.06.06a1.7 1.7 0 0 0 1.88.34 1.7 1.7 0 0 0 1.03-1.55V4h3v.09a1.7 1.7 0 0 0 1.03 1.55 1.7 1.7 0 0 0 1.88-.34l.06-.06 2.1 2.1-.06.06a1.7 1.7 0 0 0-.34 1.88 1.7 1.7 0 0 0 1.55 1.03H20v3h-.09A1.7 1.7 0 0 0 19.4 15Z" />
      </>
    ),

    help: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M9.4 9a2.7 2.7 0 1 1 4.7 1.8c-.9.9-2.1 1.4-2.1 3M12 17h.01" />
      </>
    ),

    upload: (
      <>
        <path d="M12 16V4M8 8l4-4 4 4" />
        <path d="M5 14v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5" />
      </>
    ),

    file: (
      <>
        <path d="M6 3h8l4 4v14H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" />
        <path d="M14 3v5h5M8 13h8M8 17h5" />
      </>
    ),

    remove: (
      <>
        <path d="M18 6 6 18M6 6l12 12" />
      </>
    ),

    spell: (
      <>
        <path d="M4 5h10M9 5c0 7-2 11-5 14M6 13c2 0 5-1 7-4M15 15l2-5 2 5M16 13h4" />
      </>
    ),

    link: (
      <>
        <path d="M10 13a5 5 0 0 0 7.1.1l2-2a5 5 0 0 0-7.1-7.1l-1.1 1.1" />
        <path d="M14 11a5 5 0 0 0-7.1-.1l-2 2A5 5 0 1 0 12 20l1.1-1.1" />
      </>
    ),

    search: (
      <>
        <circle cx="10.5" cy="10.5" r="6.5" />
        <path d="m16 16 4 4" />
      </>
    ),

    arrow: (
      <>
        <path d="M5 12h14M13 6l6 6-6 6" />
      </>
    ),

    chevron: <path d="m8 10 4 4 4-4" />,

    check: <path d="m5 12 4 4L19 6" />,

    document: (
      <>
        <path d="M6 3h8l4 4v14H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" />
        <path d="M14 3v5h5" />
      </>
    ),
  }

  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  )
}

const formatSize = (bytes: number) =>
  bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`

const featureById = (id: string) =>
  features.find((feature) => feature.id === id)

const pageCountLabel = (document: DocumentRecord) =>
  document.pageCount === null
    ? 'Page count available after analysis'
    : `${document.pageCount.toLocaleString()} pages`

function App() {
  const [activePage, setActivePage] = useState('Home')
  const [screen, setScreen] = useState<Screen>('home')
  const [document, setDocument] = useState<DocumentRecord | null>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [selectedFilePageCounts, setSelectedFilePageCounts] = useState<
    (number | null)[]
  >([])
  const [selectedFeatureIds, setSelectedFeatureIds] = useState<string[]>([])
  const [analysisResult, setAnalysisResult] =
    useState<AnalysisResult | null>(null)
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [viewedHistoryEntry, setViewedHistoryEntry] =
  useState<HistoryEntry | null>(null)
  useEffect(() => {
  const savedHistory = localStorage.getItem('dc-cat-history')

  if (savedHistory) {
    setHistory(JSON.parse(savedHistory))
  }
}, [])
  const [activeFinding, setActiveFinding] = useState<Finding | null>(null)
  const [progress, setProgress] = useState(0)
  const [isDragging, setIsDragging] = useState(false)
  const [fileError, setFileError] = useState('')
  const [search, setSearch] = useState('')
  const [documentFilter, setDocumentFilter] = useState('all')
  const [featureFilter, setFeatureFilter] = useState('all')
  const [keywordQuery, setKeywordQuery] = useState('')
  const [zoom, setZoom] = useState(1)
  const [viewerState, setViewerState] = useState<
    'idle' | 'loading' | 'ready' | 'error'
  >('idle')
  const [highlightBox, setHighlightBox] = useState<{
    x: number
    y: number
    width: number
    height: number
  } | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const pdfCanvasRef = useRef<HTMLCanvasElement>(null)

  const canAnalyze =
  selectedFiles.length > 0 &&
  selectedFeatureIds.length > 0 &&
  (!selectedFeatureIds.includes('keyword-search') ||
    keywordQuery.trim().length > 0)
    useEffect(() => {
    if (screen !== 'progress') return

    const interval = window.setInterval(() => {
      setProgress((current) => Math.min(current + 2, 90))
    }, 250)

    return () => window.clearInterval(interval)
  }, [screen])

    useEffect(() => {
    if (
      screen !== 'viewer' ||
      !activeFinding ||
      !selectedFile ||
      document?.type !== 'PDF'
    ) {
      return
    }

    let cancelled = false
    let loadingTask: ReturnType<typeof getDocument> | undefined

    const renderPage = async () => {
      setViewerState('loading')

      try {
        loadingTask = getDocument({
          data: new Uint8Array(await selectedFile.arrayBuffer()),
        })

        const pdf = await loadingTask.promise
        const page = await pdf.getPage(activeFinding.page)
        const viewport = page.getViewport({ scale: 1.25 * zoom })

        const textContent = await page.getTextContent()
        const targetText = activeFinding.original?.trim().toLowerCase()

        if (targetText) {
          const textItem = textContent.items.find(
            (item) =>
              'str' in item &&
              typeof item.str === 'string' &&
              item.str.toLowerCase().includes(targetText),
          )

          if (
            textItem &&
            'str' in textItem &&
            typeof textItem.str === 'string'
          ) {
            const transform = Util.transform(
              viewport.transform,
              textItem.transform,
            )

            const fontHeight = Math.hypot(transform[2], transform[3])
            const itemWidth = textItem.width * viewport.scale

            const startIndex = textItem.str
              .toLowerCase()
              .indexOf(targetText)

            const characterWidth = itemWidth / textItem.str.length

            const paddingX = 3


setHighlightBox({
  x: transform[4] + startIndex * characterWidth ,
  y: transform[5] - fontHeight + 1,
width: targetText.length * characterWidth + paddingX * 2,
height: fontHeight,
})
          } else {
            setHighlightBox(null)
          }
        } else {
          setHighlightBox(null)
        }

        const canvas = pdfCanvasRef.current
        const context = canvas?.getContext('2d')

        if (!canvas || !context || cancelled) return

        canvas.width = Math.ceil(viewport.width)
        canvas.height = Math.ceil(viewport.height)

        await page.render({
          canvas,
          canvasContext: context,
          viewport,
        }).promise

        page.cleanup()
        await pdf.cleanup()

        if (!cancelled) {
          setViewerState('ready')
        }
      } catch {
        if (!cancelled) {
          setViewerState('error')
        }
      }
    }

    void renderPage()

    return () => {
      cancelled = true
      void loadingTask?.destroy()
    }
  }, [activeFinding, document?.type, screen, selectedFile, zoom])

   const chooseFile = async (files?: FileList | File) => {
    if (!files) return

    const fileList =
      files instanceof FileList ? Array.from(files) : [files]

    if (fileList.length === 0) return

    setSelectedFiles((current) => [...current, ...fileList])

    const pageCounts = await Promise.all(
      fileList.map(async (selected) => {
        const extension = selected.name.split('.').pop()?.toLowerCase()

        if (extension !== 'pdf') {
          return null
        }

        try {
          const task = getDocument({
            data: new Uint8Array(await selected.arrayBuffer()),
          })

          const pdf = await task.promise
          const pageCount = pdf.numPages

          await pdf.cleanup()
          await task.destroy()

          return pageCount
        } catch {
          return null
        }
      }),
    )

    setSelectedFilePageCounts((current) => [
      ...current,
      ...pageCounts,
    ])

    const file = fileList[0]

    const extension = file.name.split('.').pop()?.toLowerCase()

    if (extension !== 'pdf' && extension !== 'docx') {
      setFileError('Please select a PDF or DOCX document.')
      return
    }

    if (extension === 'docx') {
      setDocument({
        name: file.name,
        type: 'DOCX',
        size: file.size,
        pageCount: null,
        pageCountSource: 'unavailable',
      })

      setSelectedFile(null)
      setFileError('')
      return
    }

    try {
      const task = getDocument({
        data: new Uint8Array(await file.arrayBuffer()),
      })

      const pdf = await task.promise
      const pageCount = pdf.numPages

      await pdf.cleanup()
      await task.destroy()

      setDocument({
        name: file.name,
        type: 'PDF',
        size: file.size,
        pageCount,
        pageCountSource: 'client',
      })

      setSelectedFile(file)
      setFileError('')
    } catch {
      setDocument(null)
      setSelectedFile(null)
      setFileError(
        'This PDF could not be read. Please choose another document.',
      )
    }
  }

    const removeDocument = (index: number) => {
  setSelectedFiles((current) =>
    current.filter((_, fileIndex) => fileIndex !== index),
  )

  setSelectedFilePageCounts((current) =>
    current.filter((_, fileIndex) => fileIndex !== index),
  )

  if (selectedFiles.length === 1) {
    setDocument(null)
    setSelectedFile(null)
    setFileError('')

    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }
}

  const toggleFeature = (id: string) =>
    setSelectedFeatureIds((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id],
    )
    const startAnalysis = async () => {
    if (!document || selectedFiles.length === 0 || !canAnalyze) return

    const formData = new FormData()

    selectedFiles.forEach((file) => {
      formData.append('files', file)
    })

    formData.append('features', selectedFeatureIds.join(','))
    formData.append('query', keywordQuery)

    setProgress(0)
    setScreen('progress')
    setActivePage('Home')

    try {
      const response = await fetch(
        `${import.meta.env.VITE_API_BASE_URL}/analyze-multiple`,
        {
          method: 'POST',
          body: formData,
        },
      )

      if (!response.ok) {
        throw new Error(`Analysis failed: ${response.status}`)
      }

      const data = await response.json()

const featureIdMap: Record<string, string> = {
        spell_check: 'spell-check',
        broken_links: 'broken-links',
        keyword_search: 'keyword-search',
        multi_doc_keyword_search: 'keyword-search',
      }



      let nextFindingId = 1

      const realFindings: Finding[] = data.documents.flatMap(
  (
    documentResult: {
          filename: string | null
          page_count: number | null
          results: Array<{
            feature: string
            findings: Array<{

              page: number | null
              message: string
              confidence?: number | null
              details?: {
                word?: string
                suggestion?: string
                incorrect_word?: string
                suggested_correction?: string
                original_sentence?: string
                corrected_sentence?: string
                paragraph_index?: number
                document_name?: string
                suggested_heading?: string | null
                suggested_page?: number | null
                reference_text?: string | null
                reference_type?: string | null
              }
            }>
          }>
            },
          documentIndex: number,
        ) =>
          documentResult.results.flatMap((result) =>
            result.findings.map((finding) => {
              const suggestedHeading = finding.details?.suggested_heading
              const suggestedPage = finding.details?.suggested_page

              return {
                id: nextFindingId++,
                documentId: String(documentIndex),
                documentName:
                  finding.details?.document_name ??
                  documentResult.filename ??
                  'Unknown document',
                page: finding.page ?? 1,
                featureId:
                  featureIdMap[result.feature] ?? result.feature,
                finding: finding.message,
                suggestion:
                  finding.details?.suggested_correction ??
                  finding.details?.suggestion ??
                  (suggestedHeading
                    ? suggestedPage
                      ? `${suggestedHeading} (p${suggestedPage})`
                      : suggestedHeading
                    : '—'),
                confidence: finding.confidence,

                original:
                  finding.details?.incorrect_word ??
                  finding.details?.word ??
                  (featureIdMap[result.feature] === 'keyword-search'
                    ? keywordQuery.trim()
                    : undefined),
                context:
                  finding.details?.original_sentence ??
                  (finding.details?.reference_type === 'Cross-reference'
                    ? finding.details?.reference_text
                    : undefined),
                correctedSentence:
                  finding.details?.corrected_sentence,
                paragraphIndex:
                  finding.details?.paragraph_index,
              }
            }),
          ),
      )

const totalPageCount = selectedFilePageCounts.reduce<number>(
  (total, pageCount) => total + (pageCount ?? 0),
  0,
)

const newResult: AnalysisResult = {
  document: {
    ...document,
    pageCount: totalPageCount,
    pageCountSource: 'client',
  },
  findings: realFindings,
  completedAt: 'Backend connected',
}
setAnalysisResult(newResult)
const historyEntry: HistoryEntry = {
  id: Date.now().toString(),
  completedAt: new Date().toISOString(),
  documents: selectedFiles.map((file) => file.name),
  documentCount: selectedFiles.length,
  pageCount: newResult.document.pageCount ?? 0,
totalFindings: newResult.findings.length,
spellCheckFindings: newResult.findings.filter(
  (finding) => finding.featureId === 'spell-check',
).length,
brokenLinksFindings: newResult.findings.filter(
  (finding) => finding.featureId === 'broken-links',
).length,
keywordSearchFindings: newResult.findings.filter(
  (finding) => finding.featureId === 'keyword-search',
).length,
result: newResult,
}

const updatedHistory = [historyEntry, ...history]

setHistory(updatedHistory)
localStorage.setItem('dc-cat-history', JSON.stringify(updatedHistory))

      setProgress(100)
      setScreen('results')
    } catch (error) {
  console.error('Analysis request failed:', error)
  setFileError('Analysis failed. Please try again.')
  setScreen('home')
}
  }
  const resetAnalysis = () => {
  setScreen('home')
  setSelectedFiles([])
  setSelectedFilePageCounts([])
  setSelectedFile(null)
  setDocument(null)
  setAnalysisResult(null)
  setActiveFinding(null)
  setViewedHistoryEntry(null)
  setProgress(0)
  setFileError('')
  setSearch('')
  setDocumentFilter('all')
  setFeatureFilter('all')
  setKeywordQuery('')
  setZoom(1)
  setViewerState('idle')
  setHighlightBox(null)

  if (fileInputRef.current) {
    fileInputRef.current.value = ''
  }
}
  const deleteHistoryEntry = (id: string) => {
    const updatedHistory = history.filter((entry) => entry.id !== id)

    setHistory(updatedHistory)
    localStorage.setItem('dc-cat-history', JSON.stringify(updatedHistory))
  }
    const navigate = (label: string) => {

    setScreen(
  label === 'Home'
    ? 'home'
    : label === 'History'
      ? 'history'
      : label === 'Reports' && analysisResult
        ? 'results'
        : 'placeholder',
)
    }

  const openFinding = (finding: Finding) => {
    const matchingFile = selectedFiles[Number(finding.documentId)]
    if (matchingFile) {
      setSelectedFile(matchingFile)

      const extension = matchingFile.name
        .split('.')
        .pop()
        ?.toLowerCase()

      if (extension === 'pdf') {
        setDocument({
          name: matchingFile.name,
          type: 'PDF',
          size: matchingFile.size,
          pageCount:
  selectedFilePageCounts[
    Number(finding.documentId)
  ] ?? null,
          pageCountSource: 'client',
        })
      }
    }

    setActiveFinding(finding)
    setZoom(1)
    setScreen('viewer')
  }
    const resultFindings = analysisResult?.findings ?? []



  const showAdjacentFinding = (offset: number) => {
  const currentIndex = filteredFindings.findIndex(
    (finding) => finding.id === activeFinding?.id,
  )

  const next = filteredFindings[currentIndex + offset]

  if (next) {
    setActiveFinding(next)
  }
}
    const exportExcel = async () => {
  if (!analysisResult) return

    const XLSX = await import('xlsx')

    const selectedFeatures = features.filter((feature) =>
      selectedFeatureIds.includes(feature.id)
    )

    const workbook = XLSX.utils.book_new()

    // -------------------------
    // Helper for readable Excel sheets
    // -------------------------
    const formatSheet = (
  sheet: import('xlsx').WorkSheet,
  widths: number[],
) => {
      sheet['!cols'] = widths.map((width) => ({ width }))

      const range = XLSX.utils.decode_range(
        sheet['!ref'] ?? 'A1'
      )

      for (let row = range.s.r; row <= range.e.r; row++) {
        for (let col = range.s.c; col <= range.e.c; col++) {
          const cell =
            sheet[
              XLSX.utils.encode_cell({
                r: row,
                c: col,
              })
            ]

          if (cell) {
            cell.s = {
              alignment: {
                vertical: 'top',
                wrapText: true,
              },
            }
          }
        }
      }
    }

    // -------------------------
    // Summary
    // -------------------------
    const summary = [
      ['Feature', 'Status', 'Findings', 'Error'],
      [
        'Total Findings',
        'Complete',
        analysisResult.findings.length,
        '',
      ],
      ...selectedFeatures.map((feature) => [
        feature.name,
        'Complete',
        analysisResult.findings.filter(
          (finding) => finding.featureId === feature.id
        ).length,
        '',
      ]),
    ]

    const summarySheet = XLSX.utils.aoa_to_sheet(summary)

    formatSheet(summarySheet, [
      28,
      16,
      12,
      30,
    ])

    XLSX.utils.book_append_sheet(
      workbook,
      summarySheet,
      'Summary'
    )

    // -------------------------
    // Spell Check
    // -------------------------
    const spellCheckFindings = analysisResult.findings
      .filter(
        (finding) => finding.featureId === 'spell-check'
      )
      .map((finding) => ({
        Document: finding.documentName,
        Page: finding.page,
        Message: `Possible spelling error: ${
          finding.original ?? finding.finding
        } → ${finding.suggestion}`,
        Confidence: '',
        'Incorrect Word': finding.original ?? '',
        'Suggested Correction':
          finding.suggestion === '—'
            ? ''
            : finding.suggestion,
        'Issue Type': 'contextual_spelling',
        'Original Sentence': finding.context ?? '',
        'Corrected Sentence':
          finding.correctedSentence ?? '',
        'Paragraph Index':
          finding.paragraphIndex ?? '',
      }))

    if (selectedFeatureIds.includes('spell-check')) {
      const sheet = XLSX.utils.json_to_sheet(
        spellCheckFindings
      )

      formatSheet(sheet, [
  28,
  10,
  55,
  14,
  24,
  24,
  55,
  55,
  18,
])

      XLSX.utils.book_append_sheet(
        workbook,
        sheet,
        'Spell Check'
      )
    }

    // -------------------------
    // Broken Links
    // -------------------------
    const brokenLinkFindings = analysisResult.findings
      .filter(
        (finding) => finding.featureId === 'broken-links'
      )
      .map((finding) => ({
        Document: finding.documentName,
        Page: finding.page,
        Message: finding.finding,
        Suggestion:
          finding.suggestion === '—'
            ? ''
            : finding.suggestion,
      }))

    if (selectedFeatureIds.includes('broken-links')) {
      const sheet = XLSX.utils.json_to_sheet(
        brokenLinkFindings
      )

      formatSheet(sheet, [
        28,
        10,
        14,
        55,
        35,
      ])

      XLSX.utils.book_append_sheet(
        workbook,
        sheet,
        'Broken Links'
      )
    }

    // -------------------------
    // Keyword Search
    // -------------------------
    const keywordSearchFindings = analysisResult.findings
      .filter(
        (finding) => finding.featureId === 'keyword-search'
      )
      .map((finding) => ({
        Document: finding.documentName,
        Page: finding.page,
        Finding: finding.finding,
      }))

    if (selectedFeatureIds.includes('keyword-search')) {
      const sheet = XLSX.utils.json_to_sheet(
        keywordSearchFindings
      )

      formatSheet(sheet, [
        28,
        10,
        40,
      ])

      XLSX.utils.book_append_sheet(
        workbook,
        sheet,
        'Keyword Search'
      )
    }

    // -------------------------
    // Download workbook
    // -------------------------
    const fileName =
      analysisResult.document.name.replace(
        /\.[^/.]+$/,
        ''
      )

    XLSX.writeFile(
      workbook,
      `DC-CAT_Report_${fileName}.xlsx`
    )
  }
    const pageAtProgress =
    document?.pageCount === null || !document
      ? null
      : Math.min(
          document.pageCount,
          Math.max(
            1,
            Math.ceil(
              (document.pageCount * progress) / 100
            )
          )
        )

  const currentStage =
    progress < 24
      ? 'Preparing document'
      : progress < 67
        ? 'Reviewing document content'
        : 'Finalizing findings'

  const filteredFindings = resultFindings.filter(
    (finding) =>
      (documentFilter === 'all' ||
        finding.documentName === documentFilter) &&
      (featureFilter === 'all' ||
        finding.featureId === featureFilter) &&

      (
        `${finding.documentName} ${finding.page} ${
          featureById(finding.featureId)?.name
        } ${finding.finding} ${finding.suggestion}`
      )
        .toLowerCase()
        .includes(search.toLowerCase())
  )

  const renderNavigation = (
    items: NavigationItem[]
  ) =>
    items.map((item) => (
      <button
        key={item.label}
        className={`nav-item ${
          activePage === item.label ? 'is-active' : ''
        }`}
        onClick={() => navigate(item.label)}
      >
        <Icon name={item.icon} />
        <span>{item.label}</span>
      </button>
    ))

    const home = (
    <section className="home-content">
      <div className="hero">
        <h1>Document Compliance Analyzer</h1>

        <p className="hero-tagline">
          Analyze. Verify. Understand.
        </p>

        <p className="hero-copy">
          Review technical documents for spelling issues, broken links, and
          important keywords.
        </p>
      </div>

      <section className="upload-section">
        <div className="section-copy">
          <h2>Start with a document</h2>

          <p>
            Upload a PDF or DOCX to begin analysis.
          </p>
        </div>

        <div
          className={`dropzone ${
            isDragging ? 'is-dragging' : ''
          } ${document ? 'has-file' : ''}`}
          onDragEnter={(event) => {
            event.preventDefault()
            setIsDragging(true)
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(event: DragEvent<HTMLDivElement>) => {
            event.preventDefault()
            setIsDragging(false)
            void chooseFile(event.dataTransfer.files)
          }}
        >
          <input
            ref={fileInputRef}
            className="visually-hidden"
            id="document-upload"
            type="file"
            multiple
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={(
              event: ChangeEvent<HTMLInputElement>
            ) =>
              void chooseFile(
                event.target.files ?? undefined
              )
            }
          />

          {selectedFiles.length > 0 ? (
            <div className="selected-files-list">
              {selectedFiles.map((file, index) => (
                <div
                  className="selected-file"
                  key={`${file.name}-${file.size}-${index}`}
                >
                  <div className="file-icon">
                    <Icon name="file" />
                  </div>

                  <div className="file-details">
                    <strong>{file.name}</strong>

                    <span>
                      {file.name
                        .toLowerCase()
                        .endsWith('.pdf')
                        ? 'PDF'
                        : 'DOCX'}{' '}
                      · {formatSize(file.size)} ·{' '}
                      {selectedFilePageCounts[index] === null
                        ? 'Page count after analysis'
                        : `${selectedFilePageCounts[index]} pages`}
                    </span>
                  </div>

                  <button
                    className="remove-file"
                    onClick={() => removeDocument(index)}
                    aria-label={`Remove ${file.name}`}
                  >
                    <Icon name="remove" />
                  </button>
                </div>
              ))}

              <label
                className="choose-button"
                htmlFor="document-upload"
              >
                Add More Documents
              </label>
            </div>
          ) : (
            <>
              <div className="upload-icon">
                <Icon name="upload" />
              </div>

              <p className="dropzone-title">
                Drag and drop your documents here
              </p>

              <p className="dropzone-or">
                or
              </p>

              <label
                className="choose-button"
                htmlFor="document-upload"
              >
                Choose Documents
              </label>
            </>
          )}
        </div>

        <p
          className={`file-hint ${
            fileError ? 'is-error' : ''
          }`}
        >
          {fileError ||
            'PDF or DOCX · Large documents supported'}
        </p>
      </section>
  <section className="analysis-section"><div className="section-heading"><div><h2>Choose analysis features</h2><p>Select one or more checks to run on your document.</p></div><button className="more-features">More features <Icon name="arrow" /></button></div><div className="feature-grid">{features.map((feature) => { const chosen = selectedFeatureIds.includes(feature.id); return <button key={feature.id} className={`feature-card ${chosen ? 'is-selected' : ''}`} onClick={() => toggleFeature(feature.id)} aria-pressed={chosen}><span className="feature-icon"><Icon name={feature.icon} /></span><span className="feature-content"><strong>{feature.name}</strong><span>{feature.description}</span></span><span className="selection-indicator">{chosen && '✓'}</span></button> })}</div></section>{selectedFeatureIds.includes('keyword-search') && (
  <div className="keyword-search-input">
    <label htmlFor="keyword-query">Keyword to search</label>
    <input
      id="keyword-query"
      type="text"
      value={keywordQuery}
      onChange={(event) => setKeywordQuery(event.target.value)}
      placeholder="Enter a keyword or phrase"
    />
  </div>
)}      <div className="analysis-action">
        <button
          className="analyze-button"
          disabled={!canAnalyze}
          onClick={startAnalysis}
        >
          Analyze Document <Icon name="arrow" />
        </button>

        {!canAnalyze && (
          <p>
            Select a document and at least one feature to continue.
          </p>
        )}
      </div>
    </section>
  )

    const progressView = document && (
    <section className="flow-content progress-content">
      <p className="view-kicker">DOCUMENT ANALYSIS</p>

      <h1>Analyzing document</h1>

      <div className="progress-document">
        <span className="progress-document-icon">
          <Icon name="document" />
        </span>

        <div>
          <strong>{document.name}</strong>
          <span>
            {document.type} · {pageCountLabel(document)}
          </span>
        </div>
      </div>

      <div className="progress-readout">
        <strong>{progress}%</strong>
        <span>{currentStage}</span>
      </div>

      <div className="progress-track">
        <span style={{ width: `${progress}%` }} />
      </div>

      <p className="page-progress">
        {pageAtProgress === null
          ? 'Page count available after analysis'
          : `Processing page ${pageAtProgress} of ${document.pageCount}`}
      </p>

      <div className="running-features">
        <p>Currently running</p>

        {features
          .filter((feature) =>
            selectedFeatureIds.includes(feature.id)
          )
          .map((feature) => (
            <div key={feature.id}>
              <span>
                <Icon name="check" />
              </span>

              {feature.name}
            </div>
          ))}
      </div>

      <button
        className="text-button cancel-button"
        onClick={resetAnalysis}
      >
        Cancel
      </button>
    </section>
  )

  const results = analysisResult && (
    <section className="flow-content results-content">
      <div className="results-heading">
        <div>
          <p className="view-kicker">ANALYSIS COMPLETE</p>

          <h1>Analysis Results</h1>

          <p className="results-document">
  {viewedHistoryEntry
    ? `${viewedHistoryEntry.documentCount} document${
        viewedHistoryEntry.documentCount !== 1 ? 's' : ''
      }`
    : `${selectedFiles.length} document${
        selectedFiles.length !== 1 ? 's' : ''
      }`}{' '}
  <span>·</span>{' '}
  {viewedHistoryEntry
    ? `${viewedHistoryEntry.pageCount} pages total`
    : `${selectedFilePageCounts.reduce<number>(
        (total, pageCount) => total + (pageCount ?? 0),
        0,
      )} pages total`}
</p>
        </div>

        <div className="results-actions">
          <button
            className="export-button"
            onClick={exportExcel}
          >
            Export Excel
          </button>

          <button
            className="text-button"
            onClick={() => setScreen('home')}
          >
            New analysis <Icon name="arrow" />
          </button>
        </div>
      </div>

      <div className="summary-grid">
        <article>
          <span>Total Findings</span>
          <strong>{analysisResult.findings.length}</strong>
        </article>

        {features
          .filter((feature) =>
            selectedFeatureIds.includes(feature.id)
          )
          .map((feature) => (
            <article key={feature.id}>
              <span>{feature.name}</span>

              <strong>
                {
                  analysisResult.findings.filter(
                    (finding) =>
                      finding.featureId === feature.id
                  ).length
                }
              </strong>
            </article>
          ))}
      </div>

      <section className="findings-section">
        <div className="findings-heading">
          <div>
            <h2>Findings</h2>
            <p>{analysisResult.completedAt}</p>
          </div>

          <div className="filters">
            <select
              value={documentFilter}
              onChange={(event) =>
                setDocumentFilter(event.target.value)
              }
            >
              <option value="all">All documents</option>

              {selectedFiles.map((file) => (
                <option
                  key={file.name}
                  value={file.name}
                >
                  {file.name}
                </option>
              ))}
            </select>

            <input
              value={search}
              onChange={(event) =>
                setSearch(event.target.value)
              }
              placeholder="Search findings"
            />

            <select
              value={featureFilter}
              onChange={(event) =>
                setFeatureFilter(event.target.value)
              }
            >
              <option value="all">All features</option>

              {features
                .filter((feature) =>
                  selectedFeatureIds.includes(feature.id)
                )
                .map((feature) => (
                  <option
                    key={feature.id}
                    value={feature.id}
                  >
                    {feature.name}
                  </option>
                ))}
            </select>


          </div>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Document</th>
                <th>Page</th>
                <th>Feature</th>
                <th>Finding</th>
                <th>Suggestion</th>
                <th>Confidence</th>
                <th>Action</th>
              </tr>
            </thead>

            <tbody>
              {filteredFindings.map((finding, index) => (
                <tr key={finding.id}>
                  <td>{index + 1}</td>
                  <td>{finding.documentName}</td>
                  <td>{finding.page}</td>
                  <td>
                    {featureById(finding.featureId)?.name}
                  </td>
                  <td>{finding.finding}</td>
                  <td>{finding.suggestion}</td>
                  <td>
                    {finding.confidence == null
                      ? ''
                      : finding.confidence.toFixed(2)}
                  </td>

                  <td>
                    <button
                      className="open-finding"
                      onClick={() => openFinding(finding)}
                    >
                      Open in document{' '}
                      <Icon name="arrow" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {filteredFindings.length === 0 && (
            <p className="no-findings">
              No findings match these filters.
            </p>
          )}
        </div>
      </section>
    </section>
  )

  const viewer = activeFinding && (
    <section className="viewer-content">
      <header className="viewer-heading">
        <button
          className="back-button"
          onClick={() => setScreen('results')}
        >
          ‹ Results
        </button>

        <div>
          <p className="view-kicker">FINDING DETAILS</p>
          <h1>Document viewer</h1>
        </div>
      </header>

      <div className="viewer-layout">
        <aside className="finding-details">
          <h2>Finding details</h2>

          <dl>
            <div>
              <dt>Feature</dt>
              <dd>
                {featureById(activeFinding.featureId)?.name}
              </dd>
            </div>

            <div>
              <dt>Page</dt>
              <dd>{activeFinding.page}</dd>
            </div>

            {activeFinding.original && (
              <div>
                <dt>Original text</dt>

                <dd>
                  <mark className="original-text">
                    {activeFinding.original}
                  </mark>
                </dd>
              </div>
            )}

            {activeFinding.suggestion &&
              activeFinding.suggestion !== '—' && (
                <div>
                  <dt>
                    {activeFinding.original
                      ? 'Suggested correction'
                      : 'Suggestion'}
                  </dt>

                  <dd>
                    <mark className="suggested-text">
                      {activeFinding.suggestion}
                    </mark>
                  </dd>
                </div>
              )}

            <div>
              <dt>Confidence</dt>

              <dd>
                {activeFinding.confidence == null
                  ? ''
                  : activeFinding.confidence.toFixed(2)}
              </dd>
            </div>


          </dl>

          {activeFinding.context && (
            <div className="context-block">
              <span>Context</span>

              <p>{activeFinding.context}</p>
            </div>
          )}
        </aside>

        <section className="document-placeholder real-document-viewer">
          <div className="viewer-toolbar">
            <span>
              Page {activeFinding.page} /{' '}
              {document?.pageCount ?? '—'}
            </span>

            <div>
              <button
                onClick={() => showAdjacentFinding(-1)}
                disabled={
  filteredFindings.findIndex(
    (finding) => finding.id === activeFinding?.id,
  ) <= 0
}
              >
                Previous
              </button>

              <button
                onClick={() => showAdjacentFinding(1)}
                disabled={
  filteredFindings.findIndex(
    (finding) => finding.id === activeFinding?.id,
  ) >=
  filteredFindings.length - 1
}
              >
                Next
              </button>

              <button
                onClick={() =>
                  setZoom((value) =>
                    Math.max(
                      0.6,
                      +(value - 0.2).toFixed(1)
                    )
                  )
                }
                aria-label="Zoom out"
              >
                −
              </button>

              <span>{Math.round(zoom * 100)}%</span>

              <button
                onClick={() =>
                  setZoom((value) =>
                    Math.min(
                      2,
                      +(value + 0.2).toFixed(1)
                    )
                  )
                }
                aria-label="Zoom in"
              >
                +
              </button>
            </div>
          </div>

          {document?.type === 'DOCX' || !selectedFile ? (
            <div className="viewer-message">
              <span className="placeholder-document-icon">
                <Icon name="document" />
              </span>

              <h2>Document preview</h2>

              <p>
                Document preview will be available after
                document processing.
              </p>
            </div>
          ) : (
            <div className="pdf-canvas-wrap">
              {viewerState === 'loading' && (
                <p className="viewer-status">
                  Loading page {activeFinding.page}…
                </p>
              )}

              {viewerState === 'error' && (
                <p className="viewer-status is-error">
                  Unable to render this page.
                </p>
              )}

              <div
                style={{
                  position: 'relative',
                  display: 'inline-block',
                }}
              >
                <canvas
                  ref={pdfCanvasRef}
                  className={
                    viewerState === 'ready'
                      ? 'is-ready'
                      : ''
                  }
                />

                {highlightBox &&
                  viewerState === 'ready' && (
                    <div
                      className="pdf-finding-highlight"
                      style={{
                        position: 'absolute',
                        left: highlightBox.x,
                        top: highlightBox.y,
                        width: highlightBox.width,
                        height: highlightBox.height,
                        backgroundColor: 'rgba(217, 48, 37, 0.18)',
                        pointerEvents: 'none',
                        boxSizing: 'border-box',
                      }}
                    />
                  )}
              </div>
            </div>
          )}
        </section>
      </div>
    </section>
  )

  const placeholder = (
    <section className="placeholder-page">
      <h1>{activePage}</h1>

      <p>
        This area is ready for a future DC-CAT workflow.
      </p>
    </section>
  )
  const historyView = (
  <section className="history-page">
    <div className="history-page-header">
      <h1>History</h1>

      {history.length > 0 && (
        <button
          className="history-clear-button"
          onClick={() => {
            setHistory([])
            localStorage.removeItem('dc-cat-history')
          }}
        >
          Erase All History
        </button>
      )}
    </div>

    {history.length === 0 ? (
      <p className="history-empty">No analysis history yet.</p>
    ) : (
      <div className="history-list">
        {history.map((entry) => (
          <article className="history-card" key={entry.id}>
            <div className="history-card-header">
  <div>
    <h2>
      {new Date(entry.completedAt).toLocaleString()}
    </h2>

    <p className="history-meta">
      {entry.documentCount} document
      {entry.documentCount !== 1 ? 's' : ''} ·{' '}
      {entry.pageCount} pages · {entry.totalFindings} findings
    </p>
  </div>

  <div className="history-card-actions">
    <button
      className="text-button"
      onClick={() => {
        setViewedHistoryEntry(entry)
        setAnalysisResult(entry.result)
        setScreen('results')
      }}
    >
      View Results <Icon name="arrow" />
    </button>

    <button
      className="history-delete-button"
      onClick={() => deleteHistoryEntry(entry.id)}
      aria-label="Delete this history entry"
      title="Delete this history entry"
    >
      <Icon name="remove" />
    </button>
  </div>
</div>

            <p className="history-documents">
              {entry.documents.join(', ')}
            </p>

            <p className="history-feature-counts">
              Spell Check: {entry.spellCheckFindings} · Broken Links:{' '}
              {entry.brokenLinksFindings} · Keyword Search:{' '}
              {entry.keywordSearchFindings}
            </p>
          </article>
        ))}
      </div>
    )}
  </section>
)

  const content =
  screen === 'home'
    ? home
    : screen === 'progress'
      ? progressView
      : screen === 'results'
        ? results
        : screen === 'viewer'
          ? viewer
          : screen === 'history'
  ? historyView
  : placeholder
  return (
    <div className="app-shell">
      <aside
        className="sidebar"
        aria-label="Primary navigation"
      >
        <div className="brand">
          <span className="nokia-mark">NOKIA</span>
          <span className="brand-divider" />
          <span className="brand-product">DC-CAT</span>
        </div>

        <nav className="navigation">
          {renderNavigation(navigation)}
        </nav>

        <nav className="navigation navigation-bottom">
          {renderNavigation(secondaryNavigation)}
        </nav>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="mobile-brand">
            <span className="nokia-mark">NOKIA</span>
            <span className="brand-divider" />
            <span className="brand-product">DC-CAT</span>
          </div>

          <button
            className="profile"
            aria-label="Open user profile"
          >
            <span className="avatar">U</span>
            <span>User</span>
            <Icon name="chevron" />
          </button>
        </header>

        {content}
      </main>
    </div>
  )
    }

export default App
