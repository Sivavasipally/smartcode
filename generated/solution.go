package main

import (
	"encoding/json"
	"log"
	"net/http"
)

// GaneshaMessage is a pydantic model for the endpoint
type GaneshaMessage struct {
	Message string `json:"message"`
}

func main() {
	http.HandleFunc("/ganesha", ganeshaHandler)
	http.ListenAndServe(":8080", nil)
}

func ganeshaHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Invalid request method", http.StatusBadRequest)
		return
	}

	message := GaneshaMessage{Message: "Om Gam Ganapathaye namaha"}
	json.NewEncoder(w).Encode(message)
}
