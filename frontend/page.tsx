"use client"

import type React from "react"
import { useState, useRef, useEffect } from "react"
import {
  Send,
  Mic,
  MicOff,
  Paperclip,
  User,
  Star,
  Activity,
  Heart,
  MessageCircle,
  TrendingUp,
  FileText,
  Headphones,
  Users,
  Key,
  X,
  Stethoscope,
  Calendar,
  ImageIcon,
  Volume2,
} from "lucide-react"

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "https://ottobiz-backend-zg2fve-56544e-212-47-72-183.sslip.io"
interface ChatMessage {
  id: string
  content: string
  sender: "user" | "ai"
  timestamp: Date
  evaluation_score?: number
  agent_used?: string
  appointment_request?: any
}

interface ChatResponse {
  response: string
  agent_used: string
  evaluation_score: number
  message_type: string
  appointment_request?: any
}

const predefinedUsers = [
  { id: "eb09b491-018b-47c3-b301-27b04539d92d", name: "John Doe" },
  { id: "3e845930-e65f-4faa-9b79-d346a600f2d3", name: "Sarah Johnson" },
  { id: "e52a80b0-9149-4ed7-9530-ccdf6a9fd0cf", name: "Michael Chen" },
  { id: "6459dc75-abc9-41cc-8470-d3add0cd326b", name: "Emily Rodriguez" },
  { id: "29512297-08f7-4885-91c5-f4fd8c85ec2b", name: "David Wilson" },
  { id: "7a7f6193-4916-4bcb-8a08-f788ca53cac0", name: "Lisa Thompson" },
  { id: "3a79a309-085b-4eef-8bbe-c6078e10e049", name: "Robert Martinez" },
  { id: "02b66530-89ab-46fc-8a7d-9856fd5f3ea4", name: "Maria Garcia" },
]

export default function Page() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      content:
        "Hello! I'm your AI healthcare assistant. Please select a user profile to start chatting. You can optionally enter your Google Gemini API key for enhanced features.",
      sender: "ai",
      timestamp: new Date(),
    },
  ])
  const [inputMessage, setInputMessage] = useState("")
  const [selectedUser, setSelectedUser] = useState<{ id: string; name: string } | null>(null)
  const [geminiApiKey, setGeminiApiKey] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [healthTip, setHealthTip] = useState("")
  const [analytics, setAnalytics] = useState<any>(null)
  const [isLoadingTip, setIsLoadingTip] = useState(false)
  const [isLoadingAnalytics, setIsLoadingAnalytics] = useState(false)
  const [isLoadingFollowUp, setIsLoadingFollowUp] = useState(false)
  const [isOnline, setIsOnline] = useState(true)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleUserSelect = (user: { id: string; name: string }) => {
    setSelectedUser(user)
    setMessages([
      {
        id: "greeting",
        content: `Hello ${user.name}! I'm your AI healthcare assistant. How can I help you today?`,
        sender: "ai",
        timestamp: new Date(),
      },
    ])
  }

  const handleSendMessage = async () => {
    if ((!inputMessage.trim() && selectedFiles.length === 0) || !selectedUser) return

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      content: inputMessage || "File(s) uploaded",
      sender: "user",
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMessage])
    const currentMessage = inputMessage
    const currentFiles = [...selectedFiles]
    setInputMessage("")
    setSelectedFiles([])
    setIsLoading(true)

    try {
      console.log("Sending message to backend:", BACKEND_URL)

      const formData = new FormData()
      formData.append("user_id", selectedUser.id)
      formData.append("message", currentMessage)

      // Only append API key if provided
      if (geminiApiKey.trim()) {
        formData.append("api_key", geminiApiKey)
      }

      currentFiles.forEach((file) => {
        formData.append("files", file)
      })

      // Try the correct endpoint path based on your backend structure
      const response = await fetch(`${BACKEND_URL}/api/v1/chat`, {
        method: "POST",
        body: formData,
      })

      console.log("Response status:", response.status)
      console.log("Response URL:", response.url)

      if (!response.ok) {
        const errorText = await response.text()
        console.error("Backend error:", errorText)
        throw new Error(`HTTP error! status: ${response.status}, message: ${errorText}`)
      }

      const data: ChatResponse = await response.json()
      console.log("Response data:", data)

      const aiMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        content: data.response,
        sender: "ai",
        timestamp: new Date(),
        evaluation_score: data.evaluation_score,
        agent_used: data.agent_used,
        appointment_request: data.appointment_request,
      }

      setMessages((prev) => [...prev, aiMessage])
    } catch (error) {
      console.error("Error sending message:", error)
      const errorMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        content: `Sorry, there was an error processing your message: ${error instanceof Error ? error.message : "Unknown error"}. Please try again.`,
        sender: "ai",
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, errorMessage])
    } finally {
      setIsLoading(false)
    }
  }

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setInputMessage(e.target.value)
  }

  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || [])
    console.log("Files selected:", files)
    setSelectedFiles((prev) => [...prev, ...files])
    // Reset the input to allow selecting the same file again
    if (event.target) {
      event.target.value = ""
    }
  }

  const handleFileUploadClick = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    console.log("File upload clicked")
    fileInputRef.current?.click()
  }

  const removeFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index))
  }

  const getFileIcon = (file: File) => {
    if (file.type.startsWith("image/")) return <ImageIcon className="w-4 h-4" />
    if (file.type.startsWith("audio/")) return <Volume2 className="w-4 h-4" />
    return <FileText className="w-4 h-4" />
  }

  const startRecording = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()

    try {
      console.log("Starting recording...")
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mediaRecorder = new MediaRecorder(stream)
      mediaRecorderRef.current = mediaRecorder
      audioChunksRef.current = []

      mediaRecorder.ondataavailable = (event) => {
        console.log("Audio data available:", event.data.size)
        audioChunksRef.current.push(event.data)
      }

      mediaRecorder.onstop = () => {
        console.log("Recording stopped")
        const audioBlob = new Blob(audioChunksRef.current, { type: "audio/wav" })
        const audioFile = new File([audioBlob], "recording.wav", { type: "audio/wav" })
        console.log("Audio file created:", audioFile)
        setSelectedFiles((prev) => [...prev, audioFile])
        stream.getTracks().forEach((track) => track.stop())
      }

      mediaRecorder.start()
      setIsRecording(true)
      console.log("Recording started")
    } catch (error) {
      console.error("Error starting recording:", error)
      alert("Error accessing microphone. Please check permissions.")
    }
  }

  const stopRecording = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()

    if (mediaRecorderRef.current && isRecording) {
      console.log("Stopping recording...")
      mediaRecorderRef.current.stop()
      setIsRecording(false)
    }
  }

  const generateHealthTip = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()

    if (!selectedUser) {
      alert("Please select a user first!")
      return
    }

    setIsLoadingTip(true)
    console.log("Generating health tip...")

    try {
      const requestBody: any = {
        user_id: selectedUser.id,
      }

      if (geminiApiKey.trim()) {
        requestBody.api_key = geminiApiKey
      }

      const response = await fetch(`${BACKEND_URL}/api/v1/health-tip/${selectedUser.id}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestBody),
      })

      console.log("Health tip response status:", response.status)

      if (!response.ok) {
        const errorText = await response.text()
        console.error("Health tip error:", errorText)
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const data = await response.json()
      console.log("Health tip data:", data)
      setHealthTip(data.health_tip || data.response || "Health tip generated successfully!")
    } catch (error) {
      console.error("Error generating health tip:", error)
      setHealthTip(
        `Error generating health tip: ${error instanceof Error ? error.message : "Unknown error"}. Please try again.`,
      )
    } finally {
      setIsLoadingTip(false)
    }
  }

  const conductFollowUp = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()

    if (!selectedUser) {
      alert("Please select a user first!")
      return
    }

    setIsLoadingFollowUp(true)
    console.log("Conducting follow-up...")

    try {
      const requestBody: any = {
        user_id: selectedUser.id,
      }

      if (geminiApiKey.trim()) {
        requestBody.api_key = geminiApiKey
      }

      const response = await fetch(`${BACKEND_URL}/api/v1/follow-up/${selectedUser.id}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestBody),
      })

      console.log("Follow-up response status:", response.status)

      if (!response.ok) {
        const errorText = await response.text()
        console.error("Follow-up error:", errorText)
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const data = await response.json()
      console.log("Follow-up data:", data)

      const followUpMessage: ChatMessage = {
        id: Date.now().toString(),
        content: data.follow_up_message,
        sender: "ai",
        timestamp: new Date(),
        agent_used: "Follow-up Agent",
      }

      setMessages((prev) => [...prev, followUpMessage])
    } catch (error) {
      console.error("Error conducting follow-up:", error)
      const errorMessage: ChatMessage = {
        id: Date.now().toString(),
        content: `Error generating follow-up questions: ${error instanceof Error ? error.message : "Unknown error"}. Please try again.`,
        sender: "ai",
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, errorMessage])
    } finally {
      setIsLoadingFollowUp(false)
    }
  }

  const getUserAnalytics = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()

    if (!selectedUser) {
      alert("Please select a user first!")
      return
    }

    setIsLoadingAnalytics(true)
    console.log("Getting user analytics...")

    try {
      const requestBody: any = {
        user_id: selectedUser.id,
      }

      if (geminiApiKey.trim()) {
        requestBody.api_key = geminiApiKey
      }

      const response = await fetch(`${BACKEND_URL}/api/v1/get_user_analytics/${selectedUser.id}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestBody),
      })

      console.log("Analytics response status:", response.status)

      if (!response.ok) {
        const errorText = await response.text()
        console.error("Analytics error:", errorText)
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const data = await response.json()
      console.log("Analytics data:", data)
      setAnalytics(data)
    } catch (error) {
      console.error("Error getting analytics:", error)
      setAnalytics({
        error: `Error fetching analytics: ${error instanceof Error ? error.message : "Unknown error"}. Please try again.`,
      })
    } finally {
      setIsLoadingAnalytics(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-purple-50">
      {/* Header */}
      <header className="bg-white shadow-lg border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-4">
            <div className="flex items-center space-x-3">
              <div className="flex items-center justify-center w-12 h-12 bg-gradient-to-r from-blue-500 to-purple-600 rounded-xl">
                <Stethoscope className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
                  Ottobiz
                </h1>
                <p className="text-sm text-gray-600">AI Automated Business Platform</p>
              </div>
            </div>
            <div className="flex items-center space-x-4">
              {selectedUser && (
                <div className="flex items-center space-x-2 bg-gradient-to-r from-blue-500 to-purple-600 text-white px-3 py-1 rounded-full">
                  <User className="w-4 h-4" />
                  <span className="text-sm font-medium">{selectedUser.name}</span>
                </div>
              )}
              <div className="flex items-center space-x-2">
                <div className={`w-2 h-2 rounded-full ${isOnline ? "bg-green-500" : "bg-red-500"}`}></div>
                <span className="text-sm text-gray-600">{isOnline ? "Online" : "Offline"}</span>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* App Capabilities Banner */}
      <div className="bg-gradient-to-r from-blue-600 to-purple-600 text-white py-4">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex flex-wrap justify-center items-center gap-6 text-sm">
            <div className="flex items-center space-x-2">
              <MessageCircle className="w-4 h-4" />
              <span>Chat Interaction</span>
            </div>
            <div className="flex items-center space-x-2">
              <Activity className="w-4 h-4" />
              <span>Follow Up</span>
            </div>
            <div className="flex items-center space-x-2">
              <Heart className="w-4 h-4" />
              <span>Health Tips</span>
            </div>
            <div className="flex items-center space-x-2">
              <Headphones className="w-4 h-4" />
              <span>Customer Service</span>
            </div>
            <div className="flex items-center space-x-2">
              <TrendingUp className="w-4 h-4" />
              <span>Analytics</span>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* Main Chat Area */}
          <div className="lg:col-span-3">
            <div className="bg-white rounded-2xl shadow-xl border border-gray-200 h-[600px] flex flex-col">
              {/* Chat Messages */}
              <div className="flex-1 overflow-y-auto p-6 space-y-4">
                {messages.map((message) => (
                  <div
                    key={message.id}
                    className={`flex ${message.sender === "user" ? "justify-end" : "justify-start"}`}
                  >
                    <div
                      className={`max-w-xs lg:max-w-md px-4 py-3 rounded-2xl ${
                        message.sender === "user"
                          ? "bg-gradient-to-r from-blue-500 to-purple-600 text-white"
                          : "bg-gray-100 text-gray-800"
                      }`}
                    >
                      <p className="text-sm">{message.content}</p>
                      <p className="text-xs opacity-75 mt-1">{message.timestamp.toLocaleTimeString()}</p>
                      {message.sender === "ai" && (
                        <div className="mt-2 space-y-1">
                          {message.evaluation_score && (
                            <div className="flex items-center space-x-1">
                              <Star className="w-3 h-3 text-yellow-500" />
                              <span className="text-xs">Score: {message.evaluation_score.toFixed(1)}</span>
                            </div>
                          )}
                          {message.agent_used && (
                            <div className="flex items-center space-x-1">
                              <Activity className="w-3 h-3 text-blue-500" />
                              <span className="text-xs">Agent: {message.agent_used}</span>
                            </div>
                          )}
                          {message.appointment_request && (
                            <div className="flex items-center space-x-1">
                              <Calendar className="w-3 h-3 text-green-500" />
                              <span className="text-xs">Appointment requested</span>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
                {isLoading && (
                  <div className="flex justify-start">
                    <div className="bg-gray-100 text-gray-800 max-w-xs lg:max-w-md px-4 py-3 rounded-2xl">
                      <p className="text-sm">Thinking...</p>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>

              {/* File Preview */}
              {selectedFiles.length > 0 && (
                <div className="px-6 pb-4">
                  <div className="flex flex-wrap gap-2">
                    {selectedFiles.map((file, index) => (
                      <div key={index} className="flex items-center space-x-2 bg-gray-100 rounded-lg px-3 py-2">
                        {getFileIcon(file)}
                        <span className="text-sm text-gray-700 truncate max-w-32">{file.name}</span>
                        <button
                          type="button"
                          onClick={() => removeFile(index)}
                          className="text-red-500 hover:text-red-700"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Input Area */}
              <div className="border-t border-gray-200 p-6">
                <div className="flex items-center space-x-3">
                  <button
                    type="button"
                    onClick={handleFileUploadClick}
                    className="p-2 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                    disabled={!selectedUser}
                  >
                    <Paperclip className="w-5 h-5" />
                  </button>
                  <button
                    type="button"
                    onClick={isRecording ? stopRecording : startRecording}
                    className={`p-2 rounded-lg transition-colors ${
                      isRecording
                        ? "text-red-600 bg-red-50 hover:bg-red-100"
                        : "text-gray-500 hover:text-blue-600 hover:bg-blue-50"
                    }`}
                    disabled={!selectedUser}
                  >
                    {isRecording ? <MicOff className="w-5 h-5" /> : <Mic className="w-5 h-5" />}
                  </button>
                  <input
                    type="text"
                    value={inputMessage}
                    onChange={handleInputChange}
                    onKeyPress={handleKeyPress}
                    placeholder={selectedUser ? "Type your health question..." : "Select a user profile first..."}
                    className="flex-1 border border-gray-300 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    disabled={isLoading || !selectedUser}
                  />
                  <button
                    type="button"
                    onClick={handleSendMessage}
                    disabled={isLoading || (!inputMessage.trim() && selectedFiles.length === 0) || !selectedUser}
                    className="bg-gradient-to-r from-blue-500 to-purple-600 text-white p-2 rounded-lg hover:from-blue-600 hover:to-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                  >
                    <Send className="w-5 h-5" />
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Sidebar */}
          <div className="space-y-6">
            {/* API Key Input */}
            <div className="bg-white rounded-2xl shadow-xl border border-gray-200 p-6">
              <div className="flex items-center space-x-2 mb-4">
                <Key className="w-5 h-5 text-blue-600" />
                <h3 className="font-semibold text-gray-800">Google Gemini API Key (Optional)</h3>
              </div>
              <p className="text-xs text-gray-600 mb-3">
                Optionally enter your Google Gemini API key for enhanced features. The app works with a default key if
                none is provided.
              </p>
              <input
                type="password"
                value={geminiApiKey}
                onChange={(e) => setGeminiApiKey(e.target.value)}
                placeholder="Enter your Gemini API key (optional)..."
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>

            {/* User Selection */}
            <div className="bg-white rounded-2xl shadow-xl border border-gray-200 p-6">
              <div className="flex items-center space-x-2 mb-4">
                <Users className="w-5 h-5 text-blue-600" />
                <h3 className="font-semibold text-gray-800">Select User Profile</h3>
              </div>
              <div className="grid grid-cols-1 gap-2 max-h-64 overflow-y-auto">
                {predefinedUsers.map((user) => (
                  <button
                    key={user.id}
                    type="button"
                    onClick={() => handleUserSelect(user)}
                    className={`p-3 rounded-lg text-left transition-all ${
                      selectedUser?.id === user.id
                        ? "bg-gradient-to-r from-blue-500 to-purple-600 text-white"
                        : "bg-gray-100 hover:bg-gray-200 text-gray-800"
                    }`}
                  >
                    <div className="font-medium text-sm">{user.name}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* Follow-up Questions */}
            <div className="bg-gradient-to-r from-green-500 to-teal-600 rounded-2xl p-6 text-white">
              <div className="flex items-center space-x-2 mb-3">
                <Activity className="w-5 h-5" />
                <h3 className="font-semibold">Follow-up Questions</h3>
              </div>
              <button
                type="button"
                onClick={conductFollowUp}
                disabled={!selectedUser || isLoadingFollowUp}
                className="w-full text-left text-sm bg-white bg-opacity-20 rounded-lg p-2 hover:bg-opacity-30 transition-all disabled:opacity-50"
              >
                {isLoadingFollowUp ? "Generating..." : "Generate Follow-up Questions"}
              </button>
            </div>

            {/* Health Tip */}
            <div className="bg-gradient-to-r from-pink-500 to-rose-600 rounded-2xl p-6 text-white">
              <div className="flex items-center space-x-2 mb-3">
                <Heart className="w-5 h-5" />
                <h3 className="font-semibold">Health Tip</h3>
              </div>
              <button
                type="button"
                onClick={generateHealthTip}
                disabled={!selectedUser || isLoadingTip}
                className="w-full text-left text-sm bg-white bg-opacity-20 rounded-lg p-2 hover:bg-opacity-30 transition-all disabled:opacity-50 mb-3"
              >
                {isLoadingTip ? "Generating..." : "Generate Health Tip"}
              </button>
              {healthTip && (
                <div className="bg-white bg-opacity-20 rounded-lg p-3">
                  <p className="text-sm opacity-90">{healthTip}</p>
                </div>
              )}
            </div>

            {/* User Analytics */}
            <div className="bg-gradient-to-r from-indigo-500 to-purple-600 rounded-2xl p-6 text-white">
              <div className="flex items-center space-x-2 mb-3">
                <TrendingUp className="w-5 h-5" />
                <h3 className="font-semibold">User Analytics</h3>
              </div>
              <button
                type="button"
                onClick={getUserAnalytics}
                disabled={!selectedUser || isLoadingAnalytics}
                className="w-full text-left text-sm bg-white bg-opacity-20 rounded-lg p-2 hover:bg-opacity-30 transition-all disabled:opacity-50 mb-3"
              >
                {isLoadingAnalytics ? "Loading..." : "Get User Analytics"}
              </button>
              {analytics && (
                <div className="bg-white bg-opacity-20 rounded-lg p-3">
                  <p className="text-sm opacity-90">
                    {analytics.error ? analytics.error : JSON.stringify(analytics, null, 2)}
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Hidden File Input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="image/*,audio/*,.pdf,.doc,.docx,.txt"
        onChange={handleFileSelect}
        className="hidden"
      />
    </div>
  )
}
