/**
 * Utilidades de saneamiento para campos de entrada de datos de usuario
 * (nombre de usuario, contraseñas, etc.).
 */

/** Longitud máxima permitida en los campos de credenciales/datos de usuario. */
export const MAX_USER_INPUT_LENGTH = 20;

/**
 * Sanea el valor de un campo donde el usuario escribe datos (nombre de
 * usuario, contraseña...):
 *
 *  · Elimina cualquier espacio en blanco (espacios, tabuladores, saltos de
 *    línea), de modo que nunca puedan existir blancos por el medio.
 *  · Limita la longitud al máximo permitido.
 *
 * Se aplica directamente en el `onChange` de los inputs para que el control
 * sea inmediato mientras el usuario teclea o pega texto.
 *
 * @param value     Valor actual del input.
 * @param maxLength Longitud máxima (por defecto {@link MAX_USER_INPUT_LENGTH}).
 * @returns El valor saneado.
 */
export function sanitizeUserInput(
  value: string,
  maxLength: number = MAX_USER_INPUT_LENGTH,
): string {
  // Quitar primero todos los espacios en blanco y luego truncar, para que el
  // límite cuente solo caracteres reales (no espacios descartados).
  return value.replace(/\s+/g, '').slice(0, maxLength);
}
