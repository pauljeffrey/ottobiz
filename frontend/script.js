class AHealthApp {
  constructor() {
    this.apiBaseUrl = window.__BACKEND_URL__ ? `${window.__BACKEND_URL__}/api/v1` : ""
    this.currentUser = null
    this.chatHistory = []
    this.notifications = []
    this.init()
  }

  async init() {
    this.setupEventListeners()
    await this.loadUsers()
    this.updateConnectionStatus()
    this.startNotificationPolling()
  }

  setupEventListeners() {
    // User selection
    document.getElementById("user-select").addEventListener("change", (e) => {
      this.selectUser(e.target.value)
    })

    // Message sending
    document.getElementById("send-btn").addEventListener("click", () => {
      this.sendMessage()
    })

    document.getElementById("message-input").addEventListener("keypress", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {  (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault()
        this.sendMessage()
      }
    })

    // File upload
    document.getElementById("file-btn").addEventListener("click", () => {
      document.getElementById("file-input").click()
    })

    document.getElementById("file-input").addEventListener("change", (e) => {
      if (e.target.files.length > 0) {
        this.sendMessageWithFile(e.target.files[0])
      }
    })

    // Agent buttons
    document.getElementById("health-tip-btn").addEventListener("click", () => {
      this.generateHealthTip()
    })

    document.getElementById("follow-up-btn").addEventListener("click", () => {
      this.conductFollowUp()
    })

    document.getElementById("medication-reminder-btn").addEventListener("click", () => {
      this.checkMedicationReminders()
    })

    document.getElementById("medical-history-btn").addEventListener("click", () => {
      this.viewMedicalHistory()
    })

    // Notification bell
    document.getElementById("notification-bell").addEventListener("click", () => {
      this.toggleNotifications()
    })
  }

  async loadUsers() {
    try {
      const response = await fetch(`${this.apiBaseUrl}/users`)
      if (!response.ok) throw new Error("Failed to load users")

      const users = await response.json()
      const select = document.getElementById("user-select")

      select.innerHTML = '<option value="">Select a user...</option>'

      users.forEach((user) => {
        const option = document.createElement("option")
        option.value = user.id
        option.textContent = `${user.name} (${user.email})`
        select.appendChild(option)
      })
    } catch (error) {
      console.error("Error loading users:", error)
      this.showError("Failed to load users. Please check your connection.")
    }
  }

  async selectUser(userId) {
    if (!userId) {
      this.currentUser = null
      this.disableChat()
      return
    }

    try {
      // Get user details
      const userResponse = await fetch(`${this.apiBaseUrl}/users/${userId}`)
      if (!userResponse.ok) throw new Error("Failed to load user")

      this.currentUser = await userResponse.json()

      // Load chat history
      const historyResponse = await fetch(`${this.apiBaseUrl}/users/${userId}/chat-history`)
      if (historyResponse.ok) {
        const historyData = await historyResponse.json()
        this.chatHistory = historyData.chat_history || []
      }

      // Load notifications
      await this.loadUserNotifications()

      this.updateUI()
      this.enableChat()
      this.displayChatHistory()
    } catch (error) {
      console.error("Error selecting user:", error)
      this.showError("Failed to load user data.")
    }
  }

  async loadUserNotifications() {
    if (!this.currentUser) return

    try {
      const response = await fetch(`${this.apiBaseUrl}/users/${this.currentUser.id}/notifications`)
      if (response.ok) {
        const data = await response.json()
        this.notifications = data.notifications || []
        this.updateNotificationUI()
      }
    } catch (error) {
      console.error("Error loading notifications:", error)
    }
  }

  updateNotificationUI() {
    const notificationCount = document.getElementById("notification-count")
    const unreadCount = this.notifications.filter(n => !n.read).length
    
    if (unreadCount > 0) {
      notificationCount.textContent = unreadCount
      notificationCount.style.display = "flex"
    } else {
      notificationCount.style.display = "none"
    }

    // Update notifications panel
    const notificationsList = document.getElementById("notifications-list")
    if (this.notifications.length > 0) {
      notificationsList.innerHTML = this.notifications.slice(0, 5).map(notification => `
        <div class="p-3 bg-white bg-opacity-60 rounded-lg ${!notification.read ? 'border-l-4 border-blue-500' : ''}">
          <div class="flex items-start justify-between">
            <div class="flex-1">
              <h4 class="font-medium text-sm">${notification.title}</h4>
              <p class="text-xs text-gray-600 mt-1">${notification.message.substring(0, 80)}...</p>
              <span class="text-xs text-gray-400">${this.formatDate(notification.created_at)}</span>
            </div>
            ${!notification.read ? '<div class="w-2 h-2 bg-blue-500 rounded-full ml-2 mt-1"></div>' : ''}
          </div>
        </div>
      `).join('')
      
      document.getElementById("notifications-panel").style.display = "block"
    }
  }

  toggleNotifications() {
    const panel = document.getElementById("notifications-panel")
    if (panel.style.display === "none" || !panel.style.display) {
      panel.style.display = "block"
    } else {
      panel.style.display = "none"
    }
  }

  updateUI() {
    if (!this.currentUser) return

    // Update current user display
    document.getElementById("current-user").textContent = `Chatting as: ${this.currentUser.name}`

    // Update user info panel
    const userInfo = document.getElementById("user-info")
    const userDetails = document.getElementById("user-details")

    const conditions = this.currentUser.medical_conditions || []
    const allergies = this.currentUser.drug_allergies || []

    userDetails.innerHTML = `
      <div class="flex items-center mb-2">
        <i class="fas fa-user w-4 mr-2 text-blue-600"></i>
        <strong>Name:</strong> <span class="ml-2">${this.currentUser.name}</span>
      </div>
      <div class="flex items-center mb-2">
        <i class="fas fa-birthday-cake w-4 mr-2 text-purple-600"></i>
        <strong>Age:</strong> <span class="ml-2">${this.currentUser.age || "N/A"}</span>
      </div>
      <div class="flex items-center mb-2">
        <i class="fas fa-venus-mars w-4 mr-2 text-pink-600"></i>
        <strong>Gender:</strong> <span class="ml-2">${this.currentUser.gender || "N/A"}</span>
      </div>
      <div class="flex items-center mb-2">
        <i class="fas fa-envelope w-4 mr-2 text-green-600"></i>
        <strong>Email:</strong> <span class="ml-2 text-xs">${this.currentUser.email}</span>
      </div>
      <div class="flex items-center mb-2">
        <i class="fas fa-phone w-4 mr-2 text-blue-600"></i>
        <strong>Phone:</strong> <span class="ml-2 text-xs">${this.currentUser.phone_number}</span>
      </div>
      ${conditions.length > 0 ? `
        <div class="mt-3 pt-3 border-t border-gray-200">
          <div class="flex items-start mb-2">
            <i class="fas fa-heartbeat w-4 mr-2 text-red-600 mt-1"></i>
            <div>
              <strong>Conditions:</strong>
              <div class="mt-1 flex flex-wrap gap-1">
                ${conditions.map(condition => `<span class="bg-red-100 text-red-800 text-xs px-2 py-1 rounded-full">${condition}</span>`).join('')}
              </div>
            </div>
          </div>
        </div>
      ` : ''}
      ${allergies.length > 0 ? `
        <div class="mt-2">
          <div class="flex items-start mb-2">
            <i class="fas fa-exclamation-triangle w-4 mr-2 text-yellow-600 mt-1"></i>
            <div>
              <strong>Allergies:</strong>
              <div class="mt-1 flex flex-wrap gap-1">
                ${allergies.map(allergy => `<span class="bg-yellow-100 text-yellow-800 text-xs px-2 py-1 rounded-full">${allergy}</span>`).join('')}
              </div>
            </div>
          </div>
        </div>
      ` : ''}
    `

    userInfo.style.display = "block"
  }

  enableChat() {
    document.getElementById("message-input").disabled = false
    document.getElementById("send-btn").disabled = false
    document.getElementById("file-btn").disabled = false
    document.getElementById("health-tip-btn").disabled = false
    document.getElementById("follow-up-btn").disabled = false
    document.getElementById("medication-reminder-btn").disabled = false
    document.getElementById("medical-history-btn").disabled = false
  }

  disableChat() {
    document.getElementById("message-input").disabled = true
    document.getElementById("send-btn").disabled = true
    document.getElementById("file-btn").disabled = true
    document.getElementById("health-tip-btn").disabled = true
    document.getElementById("follow-up-btn").disabled = true
    document.getElementById("medication-reminder-btn").disabled = true
    document.getElementById("medical-history-btn").disabled = true

    document.getElementById("user-info").style.display = "none"
    document.getElementById("notifications-panel").style.display = "none"
    this.clearChat()
  }

  displayChatHistory() {
    const messagesContainer = document.getElementById("chat-messages")
    messagesContainer.innerHTML = ""

    if (this.chatHistory.length === 0) {
      messagesContainer.innerHTML = `
        <div class="text-center text-gray-500 py-12">
          <div class="mb-6">
            <i class="fas fa-comments text-6xl text-gray-300"></i>
          </div>
          <h3 class="text-xl font-semibold mb-2">No chat history yet</h3>
          <p class="text-gray-400">Start a conversation to see your chat history here!</p>
        </div>
      `
      return
    }

    this.chatHistory.forEach((chat) => {
      this.addMessageToChat(chat.user, "user", false)
      this.addMessageToChat(chat.ai, "ai", false)
    })

    this.scrollToBottom()
  }

  addMessageToChat(message, sender, animate = true) {
    const messagesContainer = document.getElementById("chat-messages")
    const messageDiv = document.createElement("div")

    const isUser = sender === "user"
    messageDiv.className = `flex ${isUser ? "justify-end" : "justify-start"} ${animate ? "message-animation" : ""}`

    const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

    messageDiv.innerHTML = `
      <div class="max-w-xs lg:max-w-md px-6 py-4 rounded-2xl text-white ${isUser ? "user-message" : "ai-message"} relative">
        <div class="flex items-center mb-2">
          <div class="w-6 h-6 rounded-full ${isUser ? "bg-white bg-opacity-20" : "bg-white bg-opacity-20"} flex items-center justify-center mr-2">
            <i class="fas ${isUser ? "fa-user" : "fa-robot"} text-xs"></i>
          </div>
          <span class="text-xs opacity-75 font-medium">${isUser ? "You" : "A-Health AI"}</span>
          <span class="text-xs opacity-50 ml-auto">${timestamp}</span>
        </div>
        <p class="text-sm leading-relaxed">${message}</p>
        ${!isUser ? '<div class="absolute -bottom-2 left-4 w-0 h-0 border-l-8 border-r-8 border-t-8 border-l-transparent border-r-transparent border-t-pink-500"></div>' : ''}
        ${isUser ? '<div class="absolute -bottom-2 right-4 w-0 h-0 border-l-8 border-r-8 border-t-8 border-l-transparent border-r-transparent border-t-purple-600"></div>' : ''}
      </div>
    `

    messagesContainer.appendChild(messageDiv)
    this.scrollToBottom()
  }

  async sendMessage() {
    const input = document.getElementById("message-input")
    const message = input.value.trim()

    if (!message || !this.currentUser) return

    // Add user message to chat
    this.addMessageToChat(message, "user")
    input.value = ""

    // Show typing indicator
    this.showTypingIndicator()

    try {
      const response = await fetch(`${this.apiBaseUrl}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          user_id: this.currentUser.id,
          message: message,
          message_type: "text",
        }),
      })

      if (!response.ok) throw new Error("Failed to send message")

      const data = await response.json()

      // Remove typing indicator and add AI response
      this.removeTypingIndicator()
      this.addMessageToChat(data.response, "ai")
      
      this.showSuccess("Message sent successfully!")
    } catch (error) {
      console.error("Error sending message:", error)
      this.removeTypingIndicator()
      this.addMessageToChat("Sorry, I encountered an error. Please try again.", "ai")
      this.showError("Failed to send message. Please try again.")
    }
  }

  async sendMessageWithFile(file) {
    if (!this.currentUser) return

    const messageInput = document.getElementById("message-input")
    const message = messageInput.value.trim() || `I'm sharing a ${file.type} file with you.`

    // Add user message to chat
    this.addMessageToChat(`${message} [📎 ${file.name}]`, "user")
    messageInput.value = ""

    // Show typing indicator
    this.showTypingIndicator()

    try {
      const formData = new FormData()
      formData.append("user_id", this.currentUser.id)
      formData.append("message", message)
      formData.append("file", file)

      const response = await fetch(`${this.apiBaseUrl}/chat/with-file`, {
        method: "POST",
        body: formData,
      })

      if (!response.ok) throw new Error("Failed to send message with file")

      const data = await response.json()

      // Remove typing indicator and add AI response
      this.removeTypingIndicator()
      this.addMessageToChat(data.response, "ai")

      // Reset file input
      document.getElementById("file-input").value = ""
      
      this.showSuccess("File processed successfully!")
    } catch (error) {
      console.error("Error sending message with file:", error)
      this.removeTypingIndicator()
      this.addMessageToChat("Sorry, I encountered an error processing your file. Please try again.", "ai")
      this.showError("Failed to process file. Please try again.")
    }
  }

  async generateHealthTip() {
    if (!this.currentUser) return

    const button = document.getElementById("health-tip-btn")
    const result = document.getElementById("health-tip-result")

    button.disabled = true
    button.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Generating...'

    try {
      const response = await fetch(`${this.apiBaseUrl}/health-tip/${this.currentUser.id}`, {
        method: "POST",
      })

      if (!response.ok) throw new Error("Failed to generate health tip")

      const data = await response.json()

      result.innerHTML = `
        <div class="space-y-3">
          <div class="flex items-start">
            <i class="fas fa-tag text-blue-600 mr-2 mt-1"></i>
            <div>
              <strong class="text-gray-800">Category:</strong>
              <span class="ml-2 bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full">${data.tip_category}</span>
            </div>
          </div>
          <div class="flex items-start">
            <i class="fas fa-lightbulb text-yellow-600 mr-2 mt-1"></i>
            <div>
              <strong class="text-gray-800">Tip:</strong>
              <p class="mt-1 text-gray-700">${data.tip_content}</p>
            </div>
          </div>
          <div class="flex items-start">
            <i class="fas fa-user-check text-green-600 mr-2 mt-1"></i>
            <div>
              <strong class="text-gray-800">Why for you:</strong>
              <p class="mt-1 text-gray-600 text-sm">${data.personalization_reason}</p>
            </div>
          </div>
          ${data.article_link ? `
            <div class="flex items-center">
              <i class="fas fa-external-link-alt text-purple-600 mr-2"></i>
              <a href="${data.article_link}" target="_blank" class="text-purple-600 hover:text-purple-800 text-sm underline">Learn more</a>
            </div>
          ` : ""}
        </div>
      `
      result.style.display = "block"
      this.showSuccess("Health tip generated successfully!")
    } catch (error) {
      console.error("Error generating health tip:", error)
      result.innerHTML = '<div class="text-red-600 flex items-center"><i class="fas fa-exclamation-circle mr-2"></i>Failed to generate health tip. Please try again.</div>'
      result.style.display = "block"
      this.showError("Failed to generate health tip.")
    } finally {
      button.disabled = false
      button.innerHTML = '<i class="fas fa-magic mr-2"></i>Generate Health Tip'
    }
  }

  async conductFollowUp() {
    if (!this.currentUser) return

    const button = document.getElementById("follow-up-btn")
    const result = document.getElementById("follow-up-result")

    button.disabled = true
    button.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Processing...'

    try {
      const response = await fetch(`${this.apiBaseUrl}/follow-up/${this.currentUser.id}`, {
        method: "POST",
      })

      if (!response.ok) throw new Error("Failed to conduct follow-up")

      const data = await response.json()

      const urgencyColor = {
        'low': 'text-green-600',
        'medium': 'text-yellow-600',
        'high': 'text-red-600',
        'urgent': 'text-red-800'
      }[data.urgency_level] || 'text-gray-600'

      result.innerHTML = `
        <div class="space-y-3">
          <div>
            <strong class="text-gray-800 flex items-center mb-2">
              <i class="fas fa-comment-medical mr-2"></i>Follow-up Message:
            </strong>
            <p class="text-gray-700 text-sm bg-white bg-opacity-40 p-3 rounded-lg">${data.follow_up_message}</p>
          </div>
          <div class="grid grid-cols-2 gap-3 text-sm">
            <div class="flex items-center">
              <i class="fas fa-exclamation-triangle mr-2 ${urgencyColor}"></i>
              <span><strong>Urgency:</strong> <span class="${urgencyColor} capitalize">${data.urgency_level}</span></span>
            </div>
            <div class="flex items-center">
              <i class="fas fa-user-md mr-2 ${data.requires_doctor_attention ? 'text-red-600' : 'text-green-600'}"></i>
              <span><strong>Doctor Attention:</strong> ${data.requires_doctor_attention ? "Yes" : "No"}</span>
            </div>
          </div>
          ${data.recommendations.length > 0 ? `
            <div>
              <strong class="text-gray-800 flex items-center mb-2">
                <i class="fas fa-list-ul mr-2"></i>Recommendations:
              </strong>
              <ul class="list-disc list-inside text-xs space-y-1 bg-white bg-opacity-40 p-3 rounded-lg">
                ${data.recommendations.map((r) => `<li class="text-gray-700">${r}</li>`).join("")}
              </ul>
            </div>
          ` : ""}
        </div>
      `
      result.style.display = "block"
      this.showSuccess("Follow-up completed successfully!")
    } catch (error) {
      console.error("Error conducting follow-up:", error)
      result.innerHTML = '<div class="text-red-600 flex items-center"><i class="fas fa-exclamation-circle mr-2"></i>Failed to conduct follow-up. Please try again.</div>'
      result.style.display = "block"
      this.showError("Failed to conduct follow-up.")
    } finally {
      button.disabled = false
      button.innerHTML = '<i class="fas fa-clipboard-check mr-2"></i>Start Follow-up'
    }
  }

  async checkMedicationReminders() {
    if (!this.currentUser) return

    const button = document.getElementById("medication-reminder-btn")
    const result = document.getElementById("medication-reminder-result")

    button.disabled = true
    button.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Checking...'

    try {
      const response = await fetch(`${this.apiBaseUrl}/medication-reminder/${this.currentUser.id}`, {
        method: "POST",
      })

      if (!response.ok) throw new Error("Failed to check medication reminders")

      const data = await response.json()

      if (data.medication_reminders.length === 0) {
        result.innerHTML = `
          <div class="text-center py-4">
            <i class="fas fa-check-circle text-green-400 text-2xl mb-2"></i>
            <p class="text-white">No medication refills needed at this time!</p>
          </div>
        `
      } else {
        result.innerHTML = `
          <div class="space-y-3">
            <div class="flex items-center mb-3">
              <i class="fas fa-pills mr-2"></i>
              <strong>${data.total_reminders} medication(s) need attention:</strong>
            </div>
            ${data.medication_reminders.map(med => `
              <div class="bg-white bg-opacity-40 p-3 rounded-lg">
                <div class="font-medium">${med.medication_name}</div>
                <div class="text-sm opacity-90">Dosage: ${med.dosage}</div>
                <div class="text-sm ${med.days_until_refill <= 3 ? 'text-red-200 font-medium' : 'opacity-90'}">
                  ${med.days_until_refill} days until refill needed
                </div>
              </div>
            `).join('')}
          </div>
        `
      }
      
      result.style.display = "block"
      this.showSuccess("Medication check completed!")
    } catch (error) {
      console.error("Error checking medication reminders:", error)
      result.innerHTML = '<div class="text-red-200 flex items-center"><i class="fas fa-exclamation-circle mr-2"></i>Failed to check medications. Please try again.</div>'
      result.style.display = "block"
      this.showError("Failed to check medications.")
    } finally {
      button.disabled = false
      button.innerHTML = '<i class="fas fa-calendar-check mr-2"></i>Check Medications'
    }
  }

  async viewMedicalHistory() {
    if (!this.currentUser) return

    const button = document.getElementById("medical-history-btn")
    const result = document.getElementById("medical-history-result")

    button.disabled = true
    button.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Loading...'

    try {
      const response = await fetch(`${this.apiBaseUrl}/users/${this.currentUser.id}/medical-history`)

      if (!response.ok) throw new Error("Failed to load medical history")

      const data = await response.json()

      let historyHtml = ""

      if (data.user_info.medical_conditions.length > 0) {
        historyHtml += `
          <div class="mb-4">
            <strong class="flex items-center mb-2">
              <i class="fas fa-heartbeat mr-2"></i>Medical Conditions:
            </strong>
            <div class="flex flex-wrap gap-1">
              ${data.user_info.medical_conditions.map(condition => 
                `<span class="bg-white bg-opacity-40 text-xs px-2 py-1 rounded-full">${condition}</span>`
              ).join('')}
            </div>
          </div>
        `
      }

      if (data.user_info.drug_allergies.length > 0) {
        historyHtml += `
          <div class="mb-4">
            <strong class="flex items-center mb-2">
              <i class="fas fa-exclamation-triangle mr-2"></i>Drug Allergies:
            </strong>
            <div class="flex flex-wrap gap-1">
              ${data.user_info.drug_allergies.map(allergy => 
                `<span class="bg-red-200 bg-opacity-60 text-red-800 text-xs px-2 py-1 rounded-full">${allergy}</span>`
              ).join('')}
            </div>
          </div>
        `
      }

      if (data.recent_consultations.length > 0) {
        historyHtml += `
          <div class="mb-4">
            <strong class="flex items-center mb-2">
              <i class="fas fa-stethoscope mr-2"></i>Recent Consultations:
            </strong>
            <div class="space-y-2">
              ${data.recent_consultations.slice(0, 3).map((consultation) => `
                <div class="bg-white bg-opacity-40 p-2 rounded text-xs">
                  <div class="font-medium">${consultation.diagnosis || "General consultation"}</div>
                  <div class="opacity-75">${this.formatDate(consultation.created_at)}</div>
                </div>
              `).join('')}
            </div>
          </div>
        `
      }

      if (data.medications.length > 0) {
        historyHtml += `
          <div class="mb-4">
            <strong class="flex items-center mb-2">
              <i class="fas fa-pills mr-2"></i>Current Medications:
            </strong>
            <div class="space-y-2">
              ${data.medications.slice(0, 3).map((med) => `
                <div class="bg-white bg-opacity-40 p-2 rounded text-xs">
                  <div class="font-medium">${med.medication_name}</div>
                  <div class="opacity-75">${med.dosage} - ${med.frequency}</div>
                </div>
              `).join('')}
            </div>
          </div>
        `
      }

      if (data.lab_tests.length > 0) {
        historyHtml += `
          <div>
            <strong class="flex items-center mb-2">
              <i class="fas fa-vial mr-2"></i>Recent Lab Tests:
            </strong>
            <div class="space-y-2">
              ${data.lab_tests.slice(0, 2).map((test) => `
                <div class="bg-white bg-opacity-40 p-2 rounded text-xs">
                  <div class="font-medium">${test.test_name}</div>
                  <div class="opacity-75">${test.status} - ${this.formatDate(test.created_at)}</div>
                </div>
              `).join('')}
            </div>
          </div>
        `
      }

      result.innerHTML = historyHtml || "<div class='text-center py-4'>No medical history available.</div>"
      result.style.display = "block"
      this.showSuccess("Medical history loaded!")
    } catch (error) {
      console.error("Error loading medical history:", error)
      result.innerHTML = '<div class="text-red-200 flex items-center"><i class="fas fa-exclamation-circle mr-2"></i>Failed to load medical history. Please try again.</div>'
      result.style.display = "block"
      this.showError("Failed to load medical history.")
    } finally {
      button.disabled = false
      button.innerHTML = '<i class="fas fa-history mr-2"></i>View History'
    }
  }

  showTypingIndicator() {
    const messagesContainer = document.getElementById("chat-messages")
    const typingDiv = document.createElement("div")
    typingDiv.id = "typing-indicator"
    typingDiv.className = "flex justify-start message-animation"

    typingDiv.innerHTML = `
      <div class="max-w-xs lg:max-w-md px-6 py-4 rounded-2xl ai-message text-white relative">
        <div class="flex items-center mb-2">
          <div class="w-6 h-6 rounded-full bg-white bg-opacity-20 flex items-center justify-center mr-2">
            <i class="fas fa-robot text-xs"></i>
          </div>
          <span class="text-xs opacity-75 font-medium">A-Health AI</span>
        </div>
        <p class="text-sm">
          <span class="loading-dots">Thinking</span>
        </p>
        <div class="absolute -bottom-2 left-4 w-0 h-0 border-l-8 border-r-8 border-t-8 border-l-transparent border-r-transparent border-t-pink-500"></div>
      </div>
    `

    messagesContainer.appendChild(typingDiv)
    this.scrollToBottom()
  }

  removeTypingIndicator() {
    const typingIndicator = document.getElementById("typing-indicator")
    if (typingIndicator) {
      typingIndicator.remove()
    }
  }

  scrollToBottom() {
    const messagesContainer = document.getElementById("chat-messages")
    messagesContainer.scrollTop = messagesContainer.scrollHeight
  }

  clearChat() {
    document.getElementById("chat-messages").innerHTML = `
      <div class="text-center text-gray-500 py-12">
        <div class="mb-6">
          <i class="fas fa-comments text-6xl text-gray-300"></i>
        </div>
        <h3 class="text-xl font-semibold mb-2">Select a user to start chatting</h3>
        <p class="text-gray-400">Choose a user persona from the sidebar to begin a conversation.</p>
      </div>
    `
  }

  showSuccess(message) {
    const toast = document.getElementById("success-toast")
    const messageEl = document.getElementById("success-message")
    messageEl.textContent = message
    
    toast.style.transform = "translateX(0)"
    setTimeout(() => {
      toast.style.transform = "translateX(100%)"
    }, 3000)
  }

  showError(message) {
    const toast = document.getElementById("error-toast")
    const messageEl = document.getElementById("error-message")
    messageEl.textContent = message
    
    toast.style.transform = "translateX(0)"
    setTimeout(() => {
      toast.style.transform = "translateX(100%)"
    }, 3000)
  }

  updateConnectionStatus() {
    // Simple connection check
    fetch(`${this.apiBaseUrl.replace("/api/v1", "")}/health`)
      .then((response) => {
        const status = document.getElementById("connection-status")
        const indicator = status.querySelector(".status-indicator")
        const text = status.querySelector("span:last-child")
        
        if (response.ok) {
          indicator.className = "status-indicator status-online"
          text.textContent = "Connected"
        } else {
          indicator.className = "status-indicator status-offline"
          text.textContent = "Connection Issues"
        }
      })
      .catch(() => {
        const status = document.getElementById("connection-status")
        const indicator = status.querySelector(".status-indicator")
        const text = status.querySelector("span:last-child")
        
        indicator.className = "status-indicator status-offline"
        text.textContent = "Disconnected"
      })
  }

  startNotificationPolling() {
    // Poll for new notifications every 30 seconds
    setInterval(() => {
      if (this.currentUser) {
        this.loadUserNotifications()
      }
    }, 30000)
  }

  formatDate(dateString) {
    const date = new Date(dateString)
    const now = new Date()
    const diffTime = Math.abs(now - date)
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24))
    
    if (diffDays === 1) {
      return "Yesterday"
    } else if (diffDays < 7) {
      return `${diffDays} days ago`
    } else {
      return date.toLocaleDateString()
    }
  }
}

// Initialize the app when the page loads
document.addEventListener("DOMContentLoaded", () => {
  new AHealthApp()
})
