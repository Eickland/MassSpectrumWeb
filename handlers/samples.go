package handlers

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"mass-spec-server/models"

	"github.com/gorilla/mux"
)

type SampleHandler struct {
	dataPath   string
	labJournal *models.LabJournal
	samples    map[string]models.Sample
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

	// Используем h.dataPath (который теперь указывает прямо на /data)
	graphsPath := h.dataPath

	files, err := os.ReadDir(graphsPath)
	if err != nil {
		return err
	}

	// Белый список расширений для графиков
	supportedExts := map[string]bool{
		".png":  true,
		".jpg":  true,
		".jpeg": true,
		".gif":  true,
		".svg":  true,
		".pdf":  true,
	}

	for _, file := range files {
		// Игнорируем папки и скрытые файлы (начинающиеся с точки)
		if file.IsDir() || strings.HasPrefix(file.Name(), ".") {
			continue
		}

		fileName := file.Name()
		ext := strings.ToLower(filepath.Ext(fileName))

		// Пропускаем, если расширение не в белом списке (автоматически проигнорирует .xlsx)
		if !supportedExts[ext] {
			continue
		}

		nameWithoutExt := strings.TrimSuffix(fileName, filepath.Ext(fileName))

		// Ищем данные в журнале
		sampleInfo, exists := h.labJournal.Samples[nameWithoutExt]
		project := "Uncategorized"
		description := ""

		if exists {
			project = sampleInfo.Project
			description = sampleInfo.Description
		}

		// Подготавливаем объект графика
		newGraph := models.Graph{
			Name:     fileName,
			FilePath: "/data/" + fileName, // URL для фронтенда
			FileType: strings.TrimPrefix(ext, "."),
		}

		if existingSample, ok := newSamples[nameWithoutExt]; ok {
			// Если образец уже есть, добавляем график в список
			newGraph.IsMain = false
			existingSample.Graphs = append(existingSample.Graphs, newGraph)
			existingSample.HasMultiple = true
			newSamples[nameWithoutExt] = existingSample
		} else {
			// Создаем новый образец
			newGraph.IsMain = true
			newSamples[nameWithoutExt] = models.Sample{
				Name:        nameWithoutExt,
				Project:     project,
				Description: description,
				CreatedAt:   time.Now(),
				Graphs:      []models.Graph{newGraph},
				HasMultiple: false,
			}
		}
	}

	h.samples = newSamples
	log.Printf("Successfully refreshed %d samples from %s", len(h.samples), graphsPath)
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
