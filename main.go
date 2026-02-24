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
	r := mux.NewRouter()

	// Пытаемся взять путь из переменной окружения, если нет - используем дефолт
	containerDataPath := os.Getenv("DATA_PATH")
	if containerDataPath == "" {
		containerDataPath = "./data" // Для локального запуска вне Docker
	}

	// Проверка существования
	if _, err := os.Stat(containerDataPath); os.IsNotExist(err) {
		log.Fatalf("CRITICAL: Data path %s does not exist!", containerDataPath)
	}

	labJournalPath := filepath.Join(containerDataPath, "lab_journal.xlsx")
	log.Printf("Looking for lab journal at: %s", labJournalPath)

	// Загружаем данные из лаб журнала
	labData, err := models.LoadLabJournal(labJournalPath)
	if err != nil {
		log.Printf("Warning: Could not load lab journal: %v", err)
		labData = models.NewLabJournal()
	}

	// Создаем обработчики
	sampleHandler := handlers.NewSampleHandler(containerDataPath, labData)
	projectHandler := handlers.NewProjectHandler(labData)

	// Статические файлы (CSS, JS)
	r.PathPrefix("/static/").Handler(http.StripPrefix("/static/", http.FileServer(http.Dir("./static"))))

	// Сервировка файлов из папки с данными
	r.PathPrefix("/data/").Handler(http.StripPrefix("/data/", http.FileServer(http.Dir(containerDataPath))))

	// API маршруты
	r.HandleFunc("/api/samples", sampleHandler.GetAllSamples).Methods("GET")
	r.HandleFunc("/api/samples/{name}", sampleHandler.GetSample).Methods("GET")
	r.HandleFunc("/api/projects", projectHandler.GetAllProjects).Methods("GET")
	r.HandleFunc("/api/projects/{name}/samples", projectHandler.GetProjectSamples).Methods("GET")
	r.HandleFunc("/api/import", sampleHandler.ImportFromFolder).Methods("POST")

	// HTML страницы
	r.HandleFunc("/", indexHandler)
	r.HandleFunc("/samples", samplesPageHandler)

	// **УЛУЧШЕНО**: Дебаг-эндпоинт с проверкой монтирования
	r.HandleFunc("/debug/files", func(w http.ResponseWriter, r *http.Request) {
		// Проверяем содержимое корневой файловой системы
		rootFiles, _ := os.ReadDir("/")

		// Проверяем содержимое /data
		dataFiles, _ := os.ReadDir("/data")

		// Проверяем содержимое /data/windows
		var windowsFiles []os.DirEntry
		var windowsFilesList []string
		windowsFiles, err = os.ReadDir(containerDataPath)
		if err != nil {
			windowsFilesList = []string{err.Error()}
		} else {
			for _, file := range windowsFiles {
				windowsFilesList = append(windowsFilesList, file.Name())
			}
		}

		// Проверяем наличие lab_journal.xlsx
		labJournalExists := false
		if _, err := os.Stat(labJournalPath); err == nil {
			labJournalExists = true
		}

		response := map[string]interface{}{
			"container_data_path":    containerDataPath,
			"lab_journal_path":       labJournalPath,
			"lab_journal_exists":     labJournalExists,
			"root_directory":         listDirEntries(rootFiles),
			"data_directory":         listDirEntries(dataFiles),
			"windows_data_directory": windowsFilesList,
			"note":                   "Files are served from /data/ filename",
			"url_prefix":             "/data/",
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(response)
	})

	r.HandleFunc("/test", func(w http.ResponseWriter, r *http.Request) {
		http.ServeFile(w, r, "./templates/test.html")
	})

	// Запуск периодического обновления данных
	go startPeriodicUpdate(sampleHandler, 5*time.Minute)

	log.Println("Server starting on :8080")
	log.Printf("Container data path: %s", containerDataPath)
	log.Fatal(http.ListenAndServe(":8080", r))
}

// Вспомогательная функция для форматирования списка файлов
func listDirEntries(entries []os.DirEntry) []string {
	var names []string
	for _, entry := range entries {
		names = append(names, entry.Name())
	}
	return names
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
