'use client';

import React, { useState } from 'react';
import { InventoryItem } from '@/types/repricer';

interface InventoryDataGridProps {
  data: InventoryItem[];
  onDataChange: (newData: InventoryItem[]) => void;
}

export default function InventoryDataGrid({ data, onDataChange }: InventoryDataGridProps) {
  const [editingCell, setEditingCell] = useState<{ row: number; col: keyof InventoryItem } | null>(null);
  const [editingValue, setEditingValue] = useState<string | number>('');

  const handleCellClick = (rowIndex: number, colKey: keyof InventoryItem) => {
    // SKU is not editable
    if (colKey === 'sku') return;

    setEditingCell({ row: rowIndex, col: colKey });
    setEditingValue(data[rowIndex][colKey] || '');
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setEditingValue(e.target.value);
  };

  const handleInputBlur = () => {
    if (editingCell) {
      const newData = [...data];
      const { row, col } = editingCell;
      let valueToUpdate: string | number = editingValue;

      // Type conversion for numeric fields
      const numericCols: (keyof InventoryItem)[] = ['quantity', 'purchasePrice', 'plannedPrice', 'expectedProfit', 'breakEven', 'referencePrice', 'otherCost'];
      if (numericCols.includes(col)) {
        valueToUpdate = parseFloat(editingValue as string);
        if (isNaN(valueToUpdate)) {
          valueToUpdate = 0; // Default to 0 if invalid number
        }
      }

      newData[row] = { ...newData[row], [col]: valueToUpdate };
      onDataChange(newData);
      setEditingCell(null);
      setEditingValue('');
    }
  };

  const handleInputKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleInputBlur();
    }
  };

  const headers: { key: keyof InventoryItem; label: string; editable: boolean }[] = [
    { key: 'purchaseDate', label: '仕入れ日', editable: true },
    { key: 'condition', label: 'コンディション', editable: true },
    { key: 'asin', label: 'ASIN', editable: true },
    { key: 'jan', label: 'JAN', editable: true },
    { key: 'productName', label: '商品名', editable: true },
    { key: 'quantity', label: '仕入れ個数', editable: true },
    { key: 'purchasePrice', label: '仕入れ価格', editable: true },
    { key: 'plannedPrice', label: '販売予定価格', editable: true },
    { key: 'expectedProfit', label: '見込み利益', editable: true },
    { key: 'breakEven', label: '損益分岐点', editable: true },
    { key: 'comment', label: 'コメント', editable: true },
    { key: 'referencePrice', label: '参考価格', editable: true },
    { key: 'shippingMethod', label: '発送方法', editable: true },
    { key: 'supplier', label: '仕入れ先', editable: true },
    { key: 'conditionNote', label: 'コンディション説明', editable: true },
    { key: 'sku', label: 'SKU', editable: false },
    { key: 'otherCost', label: 'その他費用', editable: true },
    { key: 'priceTrace', label: '価格自動調整', editable: true },
  ];

  const priceTraceOptions = [
    { value: 0, label: '価格の自動変更をしない' },
    { value: 1, label: 'FBA状態合わせモードで自動変更' },
    { value: 2, label: '状態合わせモードで自動変更' },
    { value: 3, label: 'FBA最安値モードで自動変更' },
    { value: 4, label: '最安値モードで自動変更' },
    { value: 5, label: 'カート価格モードで自動変更（新品限定）' },
  ];

  return (
    <div className="overflow-x-auto relative shadow-md sm:rounded-lg">
      <div className="max-h-96 overflow-y-auto"> {/* Fixed height for vertical scroll */}
        <table className="w-full text-sm text-left text-gray-500 dark:text-gray-400">
          <thead className="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400 sticky top-0">
            <tr>
              {headers.map((header) => (
                <th scope="col" key={header.key} className="py-3 px-6">
                  {header.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((item, rowIndex) => (
              <tr
                key={rowIndex}
                className={`${rowIndex % 2 === 0 ? 'bg-white' : 'bg-gray-50'} border-b dark:bg-gray-800 dark:border-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600`}
              >
                {headers.map((header) => (
                  <td
                    key={header.key}
                    className={`py-4 px-6 ${header.editable ? 'cursor-pointer' : ''} ${header.key === 'sku' && item.sku ? 'bg-gray-200 text-gray-700' : ''} ${editingCell?.row === rowIndex && editingCell.col === header.key ? 'border-2 border-blue-500' : ''}`}
                    onClick={() => handleCellClick(rowIndex, header.key)}
                  >
                    {editingCell?.row === rowIndex && editingCell.col === header.key ? (
                      header.key === 'priceTrace' ? (
                        <select
                          value={editingValue}
                          onChange={handleInputChange}
                          onBlur={handleInputBlur}
                          className="w-full p-1 border rounded"
                          autoFocus
                        >
                          {priceTraceOptions.map(opt => (
                            <option key={opt.value} value={opt.value}>{opt.label}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type={header.key === 'purchasePrice' ? 'number' : 'text'}
                          value={editingValue}
                          onChange={handleInputChange}
                          onBlur={handleInputBlur}
                          onKeyPress={handleInputKeyPress}
                          className="w-full p-1 border rounded"
                          autoFocus
                        />
                      )
                    ) : (
                      header.key === 'priceTrace'
                        ? priceTraceOptions.find(opt => opt.value === item.priceTrace)?.label || item.priceTrace
                        : item[header.key]
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {data.length === 0 && (
            <div className="text-center py-4 text-gray-500">
                表示するデータがありません。
            </div>
        )}
      </div>
    </div>
  );
}
