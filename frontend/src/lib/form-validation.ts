/**
 * P3 G8: 统一表单校验工具
 * 提供常用校验器和通用校验函数，防止无效输入提交到后端。
 */

export const validators = {
  positiveNumber: (value: number): boolean => value > 0,
  minNumber: (min: number) => (value: number): boolean => value >= min,
  maxNumber: (max: number) => (value: number): boolean => value <= max,
  required: (value: string | number): boolean =>
    value !== "" && value !== 0 && value !== undefined && value !== null,
  nonEmptyString: (value: string): boolean => value.trim().length > 0,
  dateRange: (start: string, end: string): boolean => {
    if (!start || !end) return true; // 允许空（可选字段）
    return new Date(start) <= new Date(end);
  },
  nonEmptyArray: <T>(arr: T[]): boolean => arr.length > 0,
};

export interface ValidationError {
  field: string;
  message: string;
}

/**
 * 通用表单校验函数
 * @param data 表单数据对象
 * @param rules 字段 -> 校验函数映射
 * @returns 错误数组（空 = 通过）
 */
export function validateForm(
  data: Record<string, unknown>,
  rules: Record<string, { validate: (v: unknown) => boolean; message: string }>,
): ValidationError[] {
  const errors: ValidationError[] = [];
  for (const [field, rule] of Object.entries(rules)) {
    if (!rule.validate(data[field])) {
      errors.push({ field, message: rule.message });
    }
  }
  return errors;
}
