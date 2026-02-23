# Stage 1: Build
FROM golang:1.25-alpine AS builder

WORKDIR /app

# Copy go mod files
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY . .

# Build the application
RUN CGO_ENABLED=0 GOOS=linux go build -o mass-spec-server .

# Stage 2: Final image
FROM alpine:latest

#RUN apk --no-cache add ca-certificates

WORKDIR /root/

# Copy binary from builder
COPY --from=builder /app/mass-spec-server .

# Copy static files and templates
COPY --from=builder /app/static ./static
COPY --from=builder /app/templates ./templates

# Create data directory
RUN mkdir -p /data/windows

# Expose port
EXPOSE 8080

# Run the application
CMD ["./mass-spec-server"]