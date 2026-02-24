package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"mass-spec-server/handlers"
	"mass-spec-server/models"

	"github.com/gorilla/mux"
)

func main() {
	// Инициализация роутера
	r := mux.NewRouter()

	windowsDataPath := "/data/windows" // В контейнере монтируется сюда
	labJournalPath := filepath.Join(windowsDataPath, "lab_journal.xlsx")

	// Загружаем данные из лаб журнала
	labData, err := models.LoadLabJournal(labJournalPath)
	if err != nil {
		log.Printf("Warning: Could not load lab journal: %v", err)
		labData = models.NewLabJournal()
	}

	// Создаем обработчики
	// **ВАЖНО**: Передаем windowsDataPath напрямую, так как файлы лежат там
	sampleHandler := handlers.NewSampleHandler(windowsDataPath, labData)
	projectHandler := handlers.NewProjectHandler(labData)

	// Статические файлы (CSS, JS)
	r.PathPrefix("/static/").Handler(http.StripPrefix("/static/", http.FileServer(http.Dir("./static"))))

	// **ИСПРАВЛЕНО**: Сервировка файлов из корневой папки с данными
	// Так как в handlers мы теперь используем FilePath: "/data/" + fileName
	r.PathPrefix("/data/").Handler(http.StripPrefix("/data/", http.FileServer(http.Dir(windowsDataPath))))

	// API маршруты
	r.HandleFunc("/api/samples", sampleHandler.GetAllSamples).Methods("GET")
	r.HandleFunc("/api/samples/{name}", sampleHandler.GetSample).Methods("GET")
	r.HandleFunc("/api/projects", projectHandler.GetAllProjects).Methods("GET")
	r.HandleFunc("/api/projects/{name}/samples", projectHandler.GetProjectSamples).Methods("GET")
	r.HandleFunc("/api/import", sampleHandler.ImportFromFolder).Methods("POST")

	// HTML страницы
	r.HandleFunc("/", indexHandler)
	r.HandleFunc("/samples", samplesPageHandler)

	// **УЛУЧШЕНО**: Дебаг-эндпоинт для проверки файлов
	r.HandleFunc("/debug/files", func(w http.ResponseWriter, r *http.Request) {
		// Проверяем наличие lab_journal.xlsx
		labJournalExists := true
		if _, err := os.Stat(labJournalPath); os.IsNotExist(err) {
			labJournalExists = false
		}

		// Читаем файлы из папки с данными
		files, err := os.ReadDir(windowsDataPath)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		var fileList []string
		var graphFiles []string

		for _, file := range files {
			if !file.IsDir() {
				fileList = append(fileList, file.Name())
				// Проверяем расширения графических файлов
				ext := filepath.Ext(file.Name())
				supportedExts := map[string]bool{
					".png": true, ".jpg": true, ".jpeg": true,
					".gif": true, ".svg": true, ".pdf": true,
				}
				if supportedExts[ext] {
					graphFiles = append(graphFiles, file.Name())
				}
			}
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"data_path":          windowsDataPath,
			"lab_journal_path":   labJournalPath,
			"lab_journal_exists": labJournalExists,
			"all_files":          fileList,
			"graph_files":        graphFiles,
			"url_prefix":         "/data/",
			"note":               "Files are served from /data/ filename",
		})
	})

	r.HandleFunc("/test", func(w http.ResponseWriter, r *http.Request) {
		http.ServeFile(w, r, "./templates/test.html")
	})

	// Запуск периодического обновления данных
	go startPeriodicUpdate(sampleHandler, 5*time.Minute)

	log.Println("Server starting on :8080")
	log.Printf("Data path: %s", windowsDataPath)
	log.Printf("Lab journal path: %s", labJournalPath)
	log.Fatal(http.ListenAndServe(":8080", r))
}

func indexHandler(w http.ResponseWriter, r *http.Request) {
	http.ServeFile(w, r, "./templates/index.html")
}

func samplesPageHandler(w http.ResponseWriter, r *http.Request) {
	http.ServeFile(w, r, "./templates/samples.html")
}

func startPeriodicUpdate(handler *handlers.SampleHandler, interval time.Duration) {
	ticker := time.NewTicker(interval)
	for range ticker.C {
		if err := handler.RefreshSamples(); err != nil {
			log.Printf("Error refreshing samples: %v", err)
		}
	}
}
