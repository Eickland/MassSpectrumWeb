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

	windowsDataPath := "/data/windows" // В контейнере будет монтироваться сюда
	labJournalPath := filepath.Join(windowsDataPath, "lab_journal.xlsx")

	// Загружаем данные из лаб журнала
	labData, err := models.LoadLabJournal(labJournalPath)
	if err != nil {
		log.Printf("Warning: Could not load lab journal: %v", err)
		labData = models.NewLabJournal()
	}

	// Создаем обработчики
	sampleHandler := handlers.NewSampleHandler(windowsDataPath, labData)
	projectHandler := handlers.NewProjectHandler(labData)

	// Статические файлы (CSS, JS)
	r.PathPrefix("/static/").Handler(http.StripPrefix("/static/", http.FileServer(http.Dir("./static"))))

	// **ВАЖНО: Сервировка файлов из папки с данными**
	// Создаем обработчик для файлов из папки graphs
	graphsPath := filepath.Join(windowsDataPath, "graphs")
	r.PathPrefix("/data/graphs/").Handler(http.StripPrefix("/data/graphs/", http.FileServer(http.Dir(graphsPath))))

	// API маршруты
	r.HandleFunc("/api/samples", sampleHandler.GetAllSamples).Methods("GET")
	r.HandleFunc("/api/samples/{name}", sampleHandler.GetSample).Methods("GET")
	r.HandleFunc("/api/projects", projectHandler.GetAllProjects).Methods("GET")
	r.HandleFunc("/api/projects/{name}/samples", projectHandler.GetProjectSamples).Methods("GET")
	r.HandleFunc("/api/import", sampleHandler.ImportFromFolder).Methods("POST")

	// HTML страницы
	r.HandleFunc("/", indexHandler)
	r.HandleFunc("/samples", samplesPageHandler)

	// Добавьте после других маршрутов
	r.HandleFunc("/debug/files", func(w http.ResponseWriter, r *http.Request) {
		graphsPath := filepath.Join(windowsDataPath, "graphs")
		files, err := os.ReadDir(graphsPath)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		var fileList []string
		for _, file := range files {
			if !file.IsDir() {
				fileList = append(fileList, file.Name())
			}
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"graph_path": graphsPath,
			"files":      fileList,
			"url_prefix": "/data/graphs/",
		})
	})

	r.HandleFunc("/test", func(w http.ResponseWriter, r *http.Request) {
		http.ServeFile(w, r, "./templates/test.html")
	})

	// Запуск периодического обновления данных
	go startPeriodicUpdate(sampleHandler, 5*time.Minute)

	log.Println("Server starting on :8080")
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
