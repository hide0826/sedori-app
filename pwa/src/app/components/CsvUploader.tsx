'use client';

import React, { useState, useCallback, ChangeEvent, DragEvent } from 'react';
import { InventoryItem } from '@/types/repricer';

interface CsvUploaderProps {
  onUploadSuccess: (data: InventoryItem[]) => void;
}

// Define the allowed file types and size limit
const ALLOWED_FILE_TYPES = ['.csv', '.xlsx'];
const MAX_FILE_SIZE_MB = 10;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

export default function CsvUploader({ onUploadSuccess }: CsvUploaderProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState<boolean>(false);

  const validateFile = (file: File): string | null => {
    if (!file) return 'ファイルが選択されていません。';

    const fileExtension = '.' + file.name.split('.').pop();
    if (!ALLOWED_FILE_TYPES.includes(fileExtension.toLowerCase())) {
      return `許可されていないファイル形式です。${ALLOWED_FILE_TYPES.join(', ')}ファイルを選択してください。`;
    }

    if (file.size > MAX_FILE_SIZE_BYTES) {
      return `ファイルサイズが大きすぎます。${MAX_FILE_SIZE_MB}MB以下のファイルを選択してください。`;
    }

    return null; // No error
  };

  const handleFile = useCallback((file: File | null) => {
    setError(null);
    setSuccess(null);
    if (!file) {
      setSelectedFile(null);
      return;
    }

    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      setSelectedFile(null);
    } else {
      setSelectedFile(file);
    }
  }, []);

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] || null;
    handleFile(file);
    // Clear the input value to allow selecting the same file again if needed
    if (event.target) {
      event.target.value = '';
    }
  };

  const handleDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragOver(false);
    const file = event.dataTransfer.files?.[0] || null;
    handleFile(file);
  }, [handleFile]);

  const handleUpload = async () => {
    if (!selectedFile) return;

    setIsLoading(true);
    setError(null);
    setSuccess(null);

    // Mock: Simulate API call delay
    await new Promise(resolve => setTimeout(resolve, 2000));

    const mockData: InventoryItem[] = [
      { jan: '4901234567890', productName: 'テスト商品1', purchasePrice: 1000, condition: '新品' },
      { jan: '4901234567891', productName: 'テスト商品2', purchasePrice: 2000, condition: '中古' },
      { jan: '4901234567892', productName: 'テスト商品3', purchasePrice: 1500, condition: '新品' }
    ];

    setIsLoading(false);
    setSuccess('CSVアップロード成功！（モック）');
    console.log('アップロードされたファイル:', selectedFile);
    onUploadSuccess(mockData);
  };

  const dropZoneBorderColor = isDragOver
    ? 'border-blue-500' // Dragging over
    : selectedFile
      ? 'border-green-500' // File selected
      : 'border-gray-300'; // Default

  const dropZoneBgColor = isDragOver ? 'bg-blue-50' : 'bg-gray-50';

  return (
    <div className="bg-white p-6 rounded-lg shadow-md max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold mb-4 text-gray-800">仕入CSVアップロード</h2>

      <div
        className={`border-2 ${dropZoneBorderColor} ${dropZoneBgColor} border-dashed rounded-lg p-8 text-center cursor-pointer transition-all duration-300`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => document.getElementById('file-input')?.click()}
      >
        <input
          type="file"
          id="file-input"
          accept={ALLOWED_FILE_TYPES.join(',')}
          onChange={handleFileChange}
          className="hidden"
        />
        {selectedFile ? (
          <div>
            <p className="font-semibold text-gray-700">選択されたファイル:</p>
            <p className="text-blue-600 break-all">{selectedFile.name}</p>
            <p className="text-sm text-gray-500">({(selectedFile.size / 1024).toFixed(2)} KB)</p>
          </div>
        ) : (
          <div>
            <p className="text-gray-500">CSVまたはXLSXファイルをここにドラッグ＆ドロップ</p>
            <p className="text-gray-400 text-sm mt-1">または</p>
            <button
              type="button"
              className="mt-3 px-4 py-2 bg-blue-500 text-white rounded-md hover:bg-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-opacity-50"
            >
              ファイルを選択
            </button>
          </div>
        )}
      </div>

      {error && (
        <div className="mt-4 p-3 bg-red-100 border border-red-400 text-red-700 rounded-md">
          <p>エラー: {error}</p>
        </div>
      )}

      {success && (
        <div className="mt-4 p-3 bg-green-100 border border-green-400 text-green-700 rounded-md">
          <p>{success}</p>
        </div>
      )}

      <div className="mt-6 text-center">
        <button
          onClick={handleUpload}
          disabled={!selectedFile || isLoading}
          className="px-6 py-3 bg-green-500 text-white font-bold rounded-md hover:bg-green-600 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-opacity-50 disabled:bg-green-300 transition-colors duration-200"
        >
          {isLoading ? (
            <span className="flex items-center justify-center">
              <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              アップロード中...
            </span>
          ) : (
            'アップロード'
          )}
        </button>
      </div>

      <div className="mt-8 pt-6 border-t border-gray-200 text-sm text-gray-600">
        <h3 className="font-semibold mb-2">注意事項:</h3>
        <ul className="list-disc ml-5 space-y-1">
          <li>CSVまたはXLSX形式のファイルをアップロードしてください。</li>
          <li>ファイルサイズは最大{MAX_FILE_SIZE_MB}MBまでです。</li>
        </ul>
      </div>
    </div>
  );
}
