package handlers

import (
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"mass-spec-server/models"

	"github.com/gorilla/mux"
)

type SampleHandler struct {
	dataPath   string
	labJournal *models.LabJournal
	samples    map[string]models.Sample
}

func (h *SampleHandler) UploadFile(w http.ResponseWriter, r *http.Request) {
	// Лимит 32 МБ
	r.ParseMultipartForm(32 << 20)

	file, handler, err := r.FormFile("file")
	if err != nil {
		http.Error(w, "Error retrieving file", http.StatusBadRequest)
		return
	}
	defer file.Close()

	// Путь сохранения (используем h.dataPath из /data в контейнере)
	dstPath := filepath.Join(h.dataPath, handler.Filename)
	dst, err := os.Create(dstPath)
	if err != nil {
		http.Error(w, "Error saving file", http.StatusInternalServerError)
		return
	}
	defer dst.Close()

	if _, err := io.Copy(dst, file); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	// Обновляем список образцов в памяти сервера
	h.RefreshSamples()

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{"status": "success", "file": handler.Filename})
}

func NewSampleHandler(dataPath string, labJournal *models.LabJournal) *SampleHandler {
	h := &SampleHandler{
		dataPath:   dataPath,
		labJournal: labJournal,
		samples:    make(map[string]models.Sample),
	}
	h.RefreshSamples()
	return h
}

func (h *SampleHandler) RefreshSamples() error {
	newSamples := make(map[string]models.Sample)
	files, err := os.ReadDir(h.dataPath)
	if err != nil {
		return err
	}

	for _, file := range files {
		if file.IsDir() || strings.HasPrefix(file.Name(), ".") {
			continue
		}

		fileName := file.Name()
		ext := strings.ToLower(filepath.Ext(fileName))
		nameWithoutExt := strings.TrimSuffix(fileName, ext)

		// ЛОГИКА ПАРСИНГА: Разделяем по "__"
		parts := strings.SplitN(nameWithoutExt, "__", 2)
		sampleID := parts[0] // Это будет ID образца (например, ADOM_001)
		fileLabel := "Main"
		if len(parts) > 1 {
			fileLabel = parts[1] // Это описание (например, stats, spectrum_2)
		}

		// Поддерживаемые расширения (добавляем таблицы и PDF)
		supportedExts := map[string]bool{
			".png": true, ".jpg": true, ".jpeg": true,
			".xlsx": true, ".csv": true, ".pdf": true,
		}
		if !supportedExts[ext] {
			continue
		}

		// Ищем метаданные в журнале по ID образца
		sampleInfo, exists := h.labJournal.Samples[sampleID]
		project, description := "Uncategorized", ""
		if exists {
			project = sampleInfo.Project
			description = sampleInfo.Description
		}

		// Создаем объект файла
		newFile := models.Graph{
			Name:     fileLabel, // Теперь здесь красивое имя (stats, spectrum)
			FilePath: "/data/" + fileName,
			FileType: strings.TrimPrefix(ext, "."),
			IsMain:   !strings.Contains(fileName, "__"), // Главным считаем файл без суффикса
		}

		// Группировка
		if s, ok := newSamples[sampleID]; ok {
			s.Graphs = append(s.Graphs, newFile)
			s.HasMultiple = true
			newSamples[sampleID] = s
		} else {
			newSamples[sampleID] = models.Sample{
				Name:        sampleID,
				Project:     project,
				Description: description,
				Graphs:      []models.Graph{newFile},
				HasMultiple: false,
			}
		}
	}
	h.samples = newSamples
	return nil
}

// GetAllSamples возвращает все образцы
func (h *SampleHandler) GetAllSamples(w http.ResponseWriter, r *http.Request) {
	samples := make([]models.Sample, 0, len(h.samples))
	for _, sample := range h.samples {
		samples = append(samples, sample)
	}

	// Сортируем по имени
	sort.Slice(samples, func(i, j int) bool {
		return samples[i].Name < samples[j].Name
	})

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(samples)
}

// GetSample возвращает конкретный образец
func (h *SampleHandler) GetSample(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	name := vars["name"]

	sample, exists := h.samples[name]
	if !exists {
		http.Error(w, "Sample not found", http.StatusNotFound)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(sample)
}

// ImportFromFolder импортирует графики из папки
func (h *SampleHandler) ImportFromFolder(w http.ResponseWriter, r *http.Request) {
	if err := h.RefreshSamples(); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{
		"message": "Import completed successfully",
		"count":   string(rune(len(h.samples))),
	})
}
